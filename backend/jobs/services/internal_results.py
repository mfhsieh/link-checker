"""
內部連結診斷與統計查詢邏輯。
"""

import logging
from collections.abc import Iterator, Mapping
from typing import cast as typing_cast

from sqlalchemy import ColumnElement, String, and_, case, cast, desc, or_
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.sql.functions import coalesce, count
from sqlalchemy.sql.functions import sum as sql_sum

from backend.jobs.schemas import InternalResultQuery
from backend.jobs.services.query_utils import _parse_json_list, execute_paginated_query
from crawler.models import CrawlQueue, Job
from crawler.utils import JSONGroupArray, JSONObject, format_crawl_queue_item

logger: logging.Logger = logging.getLogger(__name__)


def stream_internal_results(db: DBSession, job_id: str, user_id: str) -> Iterator[dict[str, object]]:
    """
    查詢任務的內部佇列結果，並以 yield 串流回傳。

    Args:
        db (DBSession): Crawler DB Session。
        job_id (str): 任務 ID。
        user_id (str): 請求查詢的使用者 ID。

    Yields:
        dict[str, object]: 單筆內部佇列結果字典。

    Raises:
        ValueError: 找不到任務或無權限存取時拋出。
    """
    # pylint: disable=duplicate-code
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if (job.user_id or "") != (user_id or ""):
        raise ValueError("無權限存取此任務。")

    cursor = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).order_by(CrawlQueue.id).yield_per(2000)
    for q in cursor:
        yield format_crawl_queue_item(q)


def stream_internal_errors(
    db: DBSession,
    query_args: InternalResultQuery,
) -> Iterator[dict[str, object]]:
    """
    查詢任務的內部失效紀錄，並以 yield 串流回傳。

    Args:
        db (DBSession): Crawler DB Session。
        query_args (InternalResultQuery): 內部結果查詢參數。

    Yields:
        dict[str, object]: 單筆內部失敗結果字典。

    Raises:
        ValueError: 找不到任務或無權限存取時拋出。
    """
    # pylint: disable=duplicate-code
    job = db.query(Job).filter(Job.id == query_args.job_id).first()
    if not job or (job.user_id or "") != (query_args.user_id or ""):
        raise ValueError("無權限存取此任務。")

    query = db.query(CrawlQueue).filter(
        CrawlQueue.job_id == query_args.job_id,
        or_(
            CrawlQueue.status.in_(["failed", "warning"]),
            and_(CrawlQueue.is_secure == False, CrawlQueue.status != "pending"),  # pylint: disable=singleton-comparison,line-too-long  # noqa: E712
        ),
    )
    query = apply_internal_result_filters(
        query,
        status_filter=query_args.status_filter,
        search=getattr(query_args, "search", None),
        exclude=getattr(query_args, "exclude", None),
    )

    if query_args.group_by == "source":
        # 呼叫既有的分頁查詢函數，但直接索取所有匹配結果並利用它實作的聚合演算法
        fetch_args = InternalResultQuery(
            job_id=query_args.job_id,
            user_id=query_args.user_id,
            status_filter=query_args.status_filter,
            group_by=query_args.group_by,
            page=1,
            page_size=9999999,
            truncate_lists=False,
        )
        results = get_internal_errors(db, fetch_args)
        items = results["items"]
        if isinstance(items, list):
            yield from items
    else:
        cursor = query.order_by(CrawlQueue.id).yield_per(2000)
        for q in cursor:
            yield format_crawl_queue_item(q)


def apply_internal_result_filters(
    query: Query,
    status_filter: str | None = None,
    search: str | None = None,
    exclude: str | None = None,
) -> Query:
    """
    套用內部失效連結的過濾條件。

    Args:
        query (Query): SQLAlchemy 查詢物件。
        status_filter (str | None): 對應資料庫 status_category 欄位的篩選條件。
        search (str | None): 搜尋關鍵字。
        exclude (str | None): 要排除的關鍵字 (以逗號分隔)。

    Returns:
        Query: 加上過濾條件後的 SQLAlchemy 查詢物件。
    """
    if search:
        # 防範 LIKE Injection：對特殊字元進行逸出，避免攻擊者利用萬用字元發動全表掃描
        search_escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search_pattern = f"%{search_escaped}%"
        query = query.filter(
            CrawlQueue.url.like(search_pattern, escape="\\") | CrawlQueue.source_url.like(search_pattern, escape="\\")
        )

    if exclude:
        excludes = [e.strip() for e in exclude.split(",") if e.strip()]
        for exc in excludes:
            # 防範 LIKE Injection
            exc_escaped = exc.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.filter(~CrawlQueue.url.ilike(f"%{exc_escaped}%", escape="\\"))

    if not status_filter or status_filter == "all":
        return query

    if status_filter == "insecure":
        query = query.filter(
            CrawlQueue.is_secure == False,  # pylint: disable=singleton-comparison  # noqa: E712
            CrawlQueue.status != "pending",
        )
    else:
        query = query.filter(CrawlQueue.status_category == status_filter)
    return query


def _get_internal_results_summary_none(db: DBSession, job_id: str) -> dict[str, object]:
    """
    計算無分組下的內部網頁失敗統計結果。

    Args:
        db (DBSession): 資料庫連線對話物件。
        job_id (str): 任務的唯一識別碼 (UUID)。

    Returns:
        object: 包含 items, total, page, page_size 等分頁資訊與資料的字典物件。
    """
    query = db.query(
        count(CrawlQueue.id).label("total"),
        sql_sum(case((CrawlQueue.status_category == "not_found", 1), else_=0)).label("not_found"),
        sql_sum(case((CrawlQueue.status_category == "server_error", 1), else_=0)).label("server_error"),
        sql_sum(case((CrawlQueue.status_category == "blocked", 1), else_=0)).label("blocked"),
        sql_sum(case((CrawlQueue.status_category == "timeout", 1), else_=0)).label("timeout"),
        sql_sum(case((CrawlQueue.status_category == "connection_error", 1), else_=0)).label("connection_error"),
        sql_sum(case((CrawlQueue.status_category == "warning", 1), else_=0)).label("warning"),
        sql_sum(case((CrawlQueue.status_category == "other_error", 1), else_=0)).label("other_error"),
        sql_sum(case((and_(CrawlQueue.is_secure == False, CrawlQueue.status != "pending"), 1), else_=0)).label(  # pylint: disable=singleton-comparison,line-too-long  # noqa: E712
            "insecure"
        ),
    ).filter(
        CrawlQueue.job_id == job_id,
        or_(
            CrawlQueue.status.in_(["failed", "warning"]),
            and_(CrawlQueue.is_secure == False, CrawlQueue.status != "pending"),  # pylint: disable=singleton-comparison,line-too-long  # noqa: E712
        ),
    )

    stats = query.first()
    total = int(stats.total) if stats and stats.total else 0
    not_found = int(stats.not_found) if stats and stats.not_found else 0
    server_error = int(stats.server_error) if stats and stats.server_error else 0
    blocked = int(stats.blocked) if stats and stats.blocked else 0
    timeout = int(stats.timeout) if stats and stats.timeout else 0
    connection_error = int(stats.connection_error) if stats and stats.connection_error else 0
    warning = int(stats.warning) if stats and stats.warning else 0
    other_error = int(stats.other_error) if stats and stats.other_error else 0
    insecure = int(stats.insecure) if stats and stats.insecure else 0

    return {
        "total": total,
        "server_error": server_error,
        "connection_error": connection_error,
        "timeout": timeout,
        "not_found": not_found,
        "other_error": other_error,
        "warning": warning,
        "blocked": blocked,
        "insecure": insecure,
    }


def _get_internal_results_summary_grouped(db: DBSession, job_id: str, group_by: str) -> dict[str, object]:
    """
    計算分組後的內部網頁失敗統計結果。

    Args:
        db (DBSession): 資料庫連線對話物件。
        job_id (str): 任務的唯一識別碼 (UUID)。
        group_by (str): 指定聚合的分組欄位。

    Returns:
        object: 包含 items, total, page, page_size 等分頁資訊與資料的字典物件。
    """
    key_col = coalesce(CrawlQueue.source_url, "") if group_by == "source" else CrawlQueue.id

    query = db.query(
        count(key_col.distinct()).label("total"),
        count(case((CrawlQueue.status_category == "not_found", key_col), else_=None).distinct()).label("not_found"),
        count(case((CrawlQueue.status_category == "server_error", key_col), else_=None).distinct()).label(
            "server_error"
        ),
        count(case((CrawlQueue.status_category == "blocked", key_col), else_=None).distinct()).label("blocked"),
        count(case((CrawlQueue.status_category == "timeout", key_col), else_=None).distinct()).label("timeout"),
        count(case((CrawlQueue.status_category == "connection_error", key_col), else_=None).distinct()).label(
            "connection_error"
        ),
        count(case((CrawlQueue.status_category == "warning", key_col), else_=None).distinct()).label("warning"),
        count(case((CrawlQueue.status_category == "other_error", key_col), else_=None).distinct()).label("other_error"),
        count(
            case((and_(CrawlQueue.is_secure == False, CrawlQueue.status != "pending"), key_col), else_=None).distinct()  # pylint: disable=singleton-comparison,line-too-long  # noqa: E712
        ).label("insecure"),
    ).filter(
        CrawlQueue.job_id == job_id,
        or_(
            CrawlQueue.status.in_(["failed", "warning"]),
            and_(CrawlQueue.is_secure == False, CrawlQueue.status != "pending"),  # pylint: disable=singleton-comparison  # noqa: E712
        ),
    )

    stats = query.first()

    total = int(stats.total) if stats and stats.total else 0
    not_found = int(stats.not_found) if stats and stats.not_found else 0
    server_error = int(stats.server_error) if stats and stats.server_error else 0
    blocked = int(stats.blocked) if stats and stats.blocked else 0
    timeout = int(stats.timeout) if stats and stats.timeout else 0
    connection_error = int(stats.connection_error) if stats and stats.connection_error else 0
    warning = int(stats.warning) if stats and stats.warning else 0
    other_error = int(stats.other_error) if stats and stats.other_error else 0
    insecure = int(stats.insecure) if stats and stats.insecure else 0

    return {
        "total": total,
        "server_error": server_error,
        "connection_error": connection_error,
        "timeout": timeout,
        "not_found": not_found,
        "other_error": other_error,
        "warning": warning,
        "blocked": blocked,
        "insecure": insecure,
    }


def get_internal_results_summary(db: DBSession, job_id: str, user_id: str, group_by: str = "none") -> dict[str, object]:
    """
    取得任務內部網頁爬取失敗的統計摘要。

    Args:
        db (DBSession): Crawler DB Session。
        job_id (str): 任務 ID。
        user_id (str): 請求查詢的使用者 ID。
        group_by (str): 聚合方式。

    Returns:
        dict[str, object]: 內部失敗統計摘要。

    Raises:
        ValueError: 找不到任務或無權限存取時拋出。
    """
    # pylint: disable=duplicate-code
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job or (job.user_id or "") != (user_id or ""):
        raise ValueError("無權限存取此任務。")

    if group_by == "none":
        return _get_internal_results_summary_none(db, job_id)
    return _get_internal_results_summary_grouped(db, job_id, group_by)


def _get_internal_errors_grouped_by_source(
    db: DBSession,
    query_args: InternalResultQuery,
) -> dict[str, object]:
    """
    取得任務內部網頁爬取失敗的紀錄列表，並依來源網頁 (Source URL) 聚合。

    Args:
        db (DBSession): 資料庫連線對話物件。
        query_args (InternalResultQuery): 包含內部查詢、過濾與分頁參數的物件。

    Returns:
        object: 包含 items, total, page, page_size 等分頁資訊與資料的字典物件。
    """
    # 1. 定義目標物件的 JSON 結構
    target_obj = JSONObject(
        "url",
        CrawlQueue.url,
        "status",
        case(
            (CrawlQueue.status_code.isnot(None), cast(CrawlQueue.status_code, String)),
            else_="Error",
        ),
        "error_message",
        CrawlQueue.error_message,
    )

    # 2. 建立主查詢，按來源網址分群，計算失敗次數，並將失效目標聚合成 JSON 陣列
    main_q = db.query(
        CrawlQueue.source_url,
        count(CrawlQueue.id).label("occurrence_count"),
        JSONGroupArray(target_obj).label("targets"),
    ).filter(
        CrawlQueue.job_id == query_args.job_id,
        or_(
            CrawlQueue.status.in_(["failed", "warning"]),
            and_(CrawlQueue.is_secure == False, CrawlQueue.status != "pending"),  # pylint: disable=singleton-comparison  # noqa: E712
        ),
    )

    main_q = apply_internal_result_filters(
        main_q,
        status_filter=query_args.status_filter,
        search=getattr(query_args, "search", None),
        exclude=getattr(query_args, "exclude", None),
    )
    main_q = main_q.group_by(CrawlQueue.source_url)

    # 3. 動態套用欄位過濾器
    filter_map = {
        "source_url": lambda v: CrawlQueue.source_url.ilike(f"%{v}%"),
        "occurrence_count": lambda v: cast(count(CrawlQueue.id), String).ilike(f"%{v}%"),
        "targets": lambda v: cast(JSONGroupArray(target_obj), String).ilike(f"%{v}%"),
    }

    # 4. 動態套用排序規則
    sort_map = {
        "source_url": CrawlQueue.source_url,
        "occurrence_count": count(CrawlQueue.id),
        "targets": cast(JSONGroupArray(target_obj), String),
    }

    def row_mapper(row: tuple) -> dict[str, object]:
        return {
            "source_url": row[0] or "",
            "occurrence_count": row[1],
            "targets": _parse_json_list(row[2])[:10] if query_args.truncate_lists else _parse_json_list(row[2]),
        }

    # pylint: disable=duplicate-code
    return execute_paginated_query(
        query=main_q,
        query_args=query_args,
        filter_map=filter_map,
        sort_map=typing_cast(Mapping[str, ColumnElement], sort_map),
        default_sort=desc(count(CrawlQueue.id)),
        row_mapper=row_mapper,
        is_having=True,
    )


def _get_internal_errors_no_grouping(
    query: Query,
    query_args: InternalResultQuery,
) -> dict[str, object]:
    """
    取得任務內部網頁爬取失敗的紀錄列表，無聚合模式。

    Args:
        query (Query): SQLAlchemy 查詢物件。
        query_args (InternalResultQuery): 包含內部查詢、過濾與分頁參數的物件。

    Returns:
        object: 包含 items, total, page, page_size 等分頁資訊與資料的字典物件。
    """
    filter_map = {
        "target_url": lambda v: CrawlQueue.url.ilike(f"%{v}%"),
        "source_url": lambda v: CrawlQueue.source_url.ilike(f"%{v}%"),
        "http_status_code": lambda v: cast(CrawlQueue.status_code, String).ilike(f"%{v}%"),
        "error_message": lambda v: CrawlQueue.error_message.ilike(f"%{v}%"),
        "is_secure": lambda v: CrawlQueue.is_secure.is_(v in ("true", "1", "yes", "✓", "v", "t")),
    }
    sort_map = {
        "target_url": CrawlQueue.url,
        "source_url": CrawlQueue.source_url,
        "http_status_code": CrawlQueue.status_code,
        "error_message": CrawlQueue.error_message,
        "is_secure": CrawlQueue.is_secure,
    }

    # pylint: disable=duplicate-code
    return execute_paginated_query(
        query=query,
        query_args=query_args,
        filter_map=filter_map,
        sort_map=typing_cast(Mapping[str, ColumnElement], sort_map),
        default_sort=CrawlQueue.id + 0,
        row_mapper=format_crawl_queue_item,
    )


def get_internal_errors(
    db: DBSession,
    query_args: InternalResultQuery,
) -> dict[str, object]:
    """
    取得任務內部網頁爬取失敗的紀錄列表。

    Args:
        db (DBSession): Crawler DB Session。
        query_args (InternalResultQuery): 查詢內部失效結果的參數封裝。

    Returns:
        dict[str, object]: 查詢結果的字典。

    Raises:
        ValueError: 找不到任務或無權限存取時拋出。
    """
    # pylint: disable=duplicate-code
    job = db.query(Job).filter(Job.id == query_args.job_id).first()
    if not job or (job.user_id or "") != (query_args.user_id or ""):
        raise ValueError("無權限存取此任務。")

    if query_args.group_by == "source":
        return _get_internal_errors_grouped_by_source(db, query_args)

    query = db.query(CrawlQueue).filter(
        CrawlQueue.job_id == query_args.job_id,
        or_(
            CrawlQueue.status.in_(["failed", "warning"]),
            and_(CrawlQueue.is_secure == False, CrawlQueue.status != "pending"),  # pylint: disable=singleton-comparison  # noqa: E712
        ),
    )
    query = apply_internal_result_filters(
        query,
        status_filter=query_args.status_filter,
        search=getattr(query_args, "search", None),
        exclude=getattr(query_args, "exclude", None),
    )
    return _get_internal_errors_no_grouping(query, query_args)
