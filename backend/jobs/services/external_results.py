"""
外部連結結果與統計查詢邏輯。
"""

import json
import logging
from collections import defaultdict
from collections.abc import Iterator, Mapping
from typing import cast as typing_cast

from sqlalchemy import ColumnElement, Integer, String, and_, case, cast, desc
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.expression import Subquery
from sqlalchemy.sql.functions import count
from sqlalchemy.sql.functions import max as sql_max
from sqlalchemy.sql.functions import min as sql_min

from backend.jobs.schemas import JobResultQuery
from backend.jobs.services.query_utils import (
    _parse_json_list,
    execute_paginated_query,
)
from crawler.models import ExternalLink, Job, apply_job_result_filters
from crawler.utils import JSONGroupArray, JSONObject, get_domain

logger: logging.Logger = logging.getLogger(__name__)


def _get_job_results_grouped_by_target(
    db: DBSession,
    query_args: JobResultQuery,
) -> dict[str, object]:
    """
    查詢任務的外連結果，並依目標網址 (Target URL) 聚合。

    Args:
        db (DBSession): 資料庫連線對話物件。
        query_args (JobResultQuery): 包含查詢、過濾與分頁參數的物件。

    Returns:
        object: 包含 items, total, page, page_size 等分頁資訊與資料的字典物件。
    """
    # 1. 建立基礎查詢，取得目標網址與來源網址的對應關係
    base_q: Query = db.query(ExternalLink.target_url, ExternalLink.source_url).filter(
        ExternalLink.job_id == query_args.job_id
    )
    base_q = apply_job_result_filters(
        base_q, search=query_args.search, exclude=query_args.exclude, status_filter=query_args.status_filter
    )
    # 2. 建立子查詢，過濾出不重複的目標與來源網址組合
    distinct_sources: Subquery = base_q.distinct().subquery("distinct_sources")

    # 3. 建立子查詢，將不重複的來源網址按目標網址聚合成 JSON 陣列
    sources_agg: Subquery = (
        db.query(distinct_sources.c.target_url, JSONGroupArray(distinct_sources.c.source_url).label("source_urls"))
        .group_by(distinct_sources.c.target_url)
        .subquery("sources_agg")
    )

    # 4. 建立子查詢，計算各目標網址的統計數據（如 IP、HTTP 狀態、發生次數等）
    target_stats_q: Query = db.query(
        ExternalLink.target_url,
        sql_max(ExternalLink.ip_address).label("ip_address"),
        sql_min(cast(ExternalLink.is_secure, Integer)).label("is_secure"),
        sql_max(ExternalLink.http_status_code).label("http_status_code"),
        sql_max(ExternalLink.error_message).label("error_message"),
        count(ExternalLink.id).label("occurrence_count"),
    ).filter(ExternalLink.job_id == query_args.job_id)
    target_stats_q = apply_job_result_filters(
        target_stats_q, search=query_args.search, exclude=query_args.exclude, status_filter=query_args.status_filter
    )
    target_stats: Subquery = target_stats_q.group_by(ExternalLink.target_url).subquery("target_stats")

    main_q = db.query(
        target_stats.c.target_url,
        target_stats.c.ip_address,
        target_stats.c.is_secure,
        target_stats.c.http_status_code,
        target_stats.c.error_message,
        target_stats.c.occurrence_count,
        sources_agg.c.source_urls,
    ).outerjoin(sources_agg, target_stats.c.target_url == sources_agg.c.target_url)

    filter_map = {
        "target_url": lambda v: target_stats.c.target_url.ilike(f"%{v}%"),
        "ip_address": lambda v: target_stats.c.ip_address.ilike(f"%{v}%"),
        "is_secure": lambda v: target_stats.c.is_secure == (1 if v in ("true", "1", "yes", "✓", "v", "t") else 0),
        "http_status_code": lambda v: cast(target_stats.c.http_status_code, String).ilike(f"%{v}%"),
        "error_message": lambda v: target_stats.c.error_message.ilike(f"%{v}%"),
        "occurrence_count": lambda v: cast(target_stats.c.occurrence_count, String).ilike(f"%{v}%"),
        "source_urls": lambda v: cast(sources_agg.c.source_urls, String).ilike(f"%{v}%"),
    }

    # 7. 動態套用排序規則
    sort_map = {
        "target_url": target_stats.c.target_url,
        "ip_address": target_stats.c.ip_address,
        "is_secure": target_stats.c.is_secure,
        "http_status_code": target_stats.c.http_status_code,
        "error_message": target_stats.c.error_message,
        "occurrence_count": target_stats.c.occurrence_count,
        "source_urls": cast(sources_agg.c.source_urls, String),
    }

    def row_mapper(row: tuple) -> dict[str, object]:
        return {
            "target_url": row[0],
            "ip_address": row[1],
            "is_secure": bool(row[2]),
            "http_status_code": row[3],
            "error_message": row[4],
            "occurrence_count": row[5],
            "source_urls": sorted(_parse_json_list(row[6]))[:10],
        }

    return execute_paginated_query(
        query=main_q,
        query_args=query_args,
        filter_map=filter_map,
        sort_map=typing_cast(Mapping[str, ColumnElement], sort_map),
        default_sort=desc(target_stats.c.occurrence_count),
        row_mapper=row_mapper,
    )


def _get_job_results_grouped_by_source(
    db: DBSession,
    query_args: JobResultQuery,
) -> dict[str, object]:
    """
    查詢任務的外連結果，並依來源網頁 (Source URL) 聚合。

    Args:
        db (DBSession): 資料庫連線對話物件。
        query_args (JobResultQuery): 包含查詢、過濾與分頁參數的物件。

    Returns:
        object: 包含 items, total, page, page_size 等分頁資訊與資料的字典物件。
    """
    # 1. 定義目標物件的 JSON 結構，動態判斷狀態字串與錯誤訊息
    target_obj = JSONObject(
        "url",
        ExternalLink.target_url,
        "status",
        case(
            (ExternalLink.http_status_code.isnot(None), cast(ExternalLink.http_status_code, String)),
            ((ExternalLink.ip_address.is_(None)) | (ExternalLink.ip_address == ""), "DNS Failed"),
            else_="Error",
        ),
        "is_secure",
        ExternalLink.is_secure,
        "error_message",
        ExternalLink.error_message,
    )

    # 2. 建立主查詢，按來源網址分群，計算總發生次數，並將目標物件聚合成 JSON 陣列
    main_q = db.query(
        ExternalLink.source_url,
        count(ExternalLink.id).label("occurrence_count"),
        JSONGroupArray(target_obj).label("targets"),
    ).filter(ExternalLink.job_id == query_args.job_id)

    main_q = apply_job_result_filters(
        main_q, search=query_args.search, exclude=query_args.exclude, status_filter=query_args.status_filter
    )
    main_q = main_q.group_by(ExternalLink.source_url)

    # 3. 動態套用欄位過濾器 (利用 .having 對聚合後的欄位過濾)
    filter_map = {
        "source_url": lambda v: ExternalLink.source_url.ilike(f"%{v}%"),
        "occurrence_count": lambda v: cast(count(ExternalLink.id), String).ilike(f"%{v}%"),
        "targets": lambda v: cast(JSONGroupArray(target_obj), String).ilike(f"%{v}%"),
    }

    # 4. 動態套用排序規則
    sort_map = {
        "source_url": ExternalLink.source_url,
        "occurrence_count": count(ExternalLink.id),
        "targets": cast(JSONGroupArray(target_obj), String),
    }

    def row_mapper(row: tuple) -> dict[str, object]:
        targets = row[2]
        if isinstance(targets, str):
            try:
                targets = json.loads(targets)
            except json.JSONDecodeError:
                targets = []

        return {
            "source_url": row[0],
            "occurrence_count": row[1],
            "targets": targets[:10],
        }

    # pylint: disable=duplicate-code
    return execute_paginated_query(
        query=main_q,
        query_args=query_args,
        filter_map=filter_map,
        sort_map=typing_cast(Mapping[str, ColumnElement], sort_map),
        default_sort=desc(count(ExternalLink.id)),
        row_mapper=row_mapper,
        is_having=True,
    )


def _get_job_results_grouped_by_domain(
    db: DBSession,
    query_args: JobResultQuery,
) -> dict[str, object]:
    """
    查詢任務的外連結果，並依外部網域 (Domain) 聚合。

    Args:
        db (DBSession): 資料庫連線對話物件。
        query_args (JobResultQuery): 包含查詢、過濾與分頁參數的物件。

    Returns:
        object: 包含 items, total, page, page_size 等分頁資訊與資料的字典物件。
    """
    # 1. 建立基礎查詢，提取目標網域、目標網址與來源網址的關係
    base_q: Query = db.query(ExternalLink.target_domain, ExternalLink.target_url, ExternalLink.source_url).filter(
        ExternalLink.job_id == query_args.job_id
    )
    base_q = apply_job_result_filters(
        base_q, search=query_args.search, exclude=query_args.exclude, status_filter=query_args.status_filter
    )

    # 2. 建立子查詢，計算各目標網域的總出現次數
    domain_stats = (
        base_q.with_entities(ExternalLink.target_domain, count(ExternalLink.id).label("occurrence_count"))
        .group_by(ExternalLink.target_domain)
        .subquery("domain_stats")
    )

    # 3. 建立子查詢，過濾不重複的目標網址，並按網域計算數量與聚合成 JSON 陣列
    distinct_urls = (
        base_q.with_entities(ExternalLink.target_domain, ExternalLink.target_url).distinct().subquery("distinct_urls")
    )
    urls_agg = (
        db.query(
            distinct_urls.c.target_domain,
            count(distinct_urls.c.target_url).label("unique_urls_count"),
            JSONGroupArray(distinct_urls.c.target_url).label("unique_urls"),
        )
        .group_by(distinct_urls.c.target_domain)
        .subquery("urls_agg")
    )

    # 4. 建立子查詢，過濾不重複的來源網址，並按網域聚合成 JSON 陣列
    distinct_sources = (
        base_q.with_entities(ExternalLink.target_domain, ExternalLink.source_url)
        .distinct()
        .subquery("distinct_sources")
    )
    sources_agg = (
        db.query(distinct_sources.c.target_domain, JSONGroupArray(distinct_sources.c.source_url).label("source_urls"))
        .group_by(distinct_sources.c.target_domain)
        .subquery("sources_agg")
    )

    # 5. 組合主查詢，以 domain_stats 為基準，外部關聯 urls_agg 與 sources_agg
    main_q = (
        db.query(
            domain_stats.c.target_domain.label("domain"),
            domain_stats.c.occurrence_count,
            urls_agg.c.unique_urls_count,
            urls_agg.c.unique_urls,
            sources_agg.c.source_urls,
        )
        .outerjoin(urls_agg, domain_stats.c.target_domain == urls_agg.c.target_domain)
        .outerjoin(sources_agg, domain_stats.c.target_domain == sources_agg.c.target_domain)
    )

    # 6. 動態套用欄位過濾器 (利用 .filter 進行過濾，因資料已在子查詢聚合完畢)
    filter_map = {
        "domain": lambda v: domain_stats.c.target_domain.ilike(f"%{v}%"),
        "occurrence_count": lambda v: cast(domain_stats.c.occurrence_count, String).ilike(f"%{v}%"),
        "unique_urls_count": lambda v: cast(urls_agg.c.unique_urls_count, String).ilike(f"%{v}%"),
        "unique_urls": lambda v: cast(urls_agg.c.unique_urls, String).ilike(f"%{v}%"),
        "source_urls": lambda v: cast(sources_agg.c.source_urls, String).ilike(f"%{v}%"),
    }

    # 7. 動態套用排序規則
    sort_map = {
        "domain": domain_stats.c.target_domain,
        "occurrence_count": domain_stats.c.occurrence_count,
        "unique_urls_count": urls_agg.c.unique_urls_count,
        "unique_urls": cast(urls_agg.c.unique_urls, String),
        "source_urls": cast(sources_agg.c.source_urls, String),
    }

    def row_mapper(row: tuple) -> dict[str, object]:
        return {
            "domain": row[0] or "unknown",
            "occurrence_count": row[1],
            "unique_urls_count": row[2] or 0,
            "unique_urls": sorted(_parse_json_list(row[3]))[:10],
            "source_urls": sorted(_parse_json_list(row[4]))[:10],
        }

    return execute_paginated_query(
        query=main_q,
        query_args=query_args,
        filter_map=filter_map,
        sort_map=typing_cast(Mapping[str, ColumnElement], sort_map),
        default_sort=desc(domain_stats.c.occurrence_count),
        row_mapper=row_mapper,
    )


def _get_job_results_no_grouping(
    query: Query,
    query_args: JobResultQuery,
) -> dict[str, object]:
    """
    查詢任務的外連結果，無聚合模式。

    Args:
        query (Query): SQLAlchemy 查詢物件。
        query_args (JobResultQuery): 包含查詢、過濾與分頁參數的物件。

    Returns:
        object: 包含 items, total, page, page_size 等分頁資訊與資料的字典物件。
    """
    filter_map = {
        "target_url": lambda v: ExternalLink.target_url.ilike(f"%{v}%"),
        "source_url": lambda v: ExternalLink.source_url.ilike(f"%{v}%"),
        "ip_address": lambda v: ExternalLink.ip_address.ilike(f"%{v}%"),
        "is_secure": lambda v: ExternalLink.is_secure.is_(v in ("true", "1", "yes", "✓", "v", "t")),
        "http_status_code": lambda v: cast(ExternalLink.http_status_code, String).ilike(f"%{v}%"),
        "error_message": lambda v: ExternalLink.error_message.ilike(f"%{v}%"),
    }

    sort_map = {
        "target_url": ExternalLink.target_url,
        "source_url": ExternalLink.source_url,
        "ip_address": ExternalLink.ip_address,
        "is_secure": ExternalLink.is_secure,
        "http_status_code": ExternalLink.http_status_code,
        "error_message": ExternalLink.error_message,
    }

    def row_mapper(lnk: ExternalLink) -> dict[str, object]:
        return {
            "id": lnk.id,
            "source_url": lnk.source_url,
            "target_url": lnk.target_url,
            "ip_address": lnk.ip_address,
            "is_secure": lnk.is_secure,
            "http_status_code": lnk.http_status_code,
            "error_message": lnk.error_message,
            "created_at": lnk.created_at.isoformat(),
            "updated_at": lnk.updated_at.isoformat(),
        }

    # pylint: disable=duplicate-code
    return execute_paginated_query(
        query=query,
        query_args=query_args,
        filter_map=filter_map,
        sort_map=typing_cast(Mapping[str, ColumnElement], sort_map),
        default_sort=ExternalLink.id + 0,
        row_mapper=row_mapper,
    )


def get_job_results(
    db: DBSession,
    query_args: JobResultQuery,
) -> dict[str, object]:
    """
    查詢任務的外連結果，支援篩選、搜尋、去重聚合與分頁。

    Args:
        db (DBSession): Crawler DB Session。
        query_args (JobResultQuery): 結果查詢參數。

    Returns:
        dict[str, object]: 查詢結果的字典。

    Raises:
        ValueError: 找不到任務或無權限存取時拋出。
    """
    # pylint: disable=duplicate-code
    job = db.query(Job).filter(Job.id == query_args.job_id).first()
    if not job:
        raise ValueError(f"找不到任務 ID: {query_args.job_id}")
    if (job.user_id or "") != (query_args.user_id or ""):
        raise ValueError("無權限存取此任務。")

    if query_args.group_by == "target":
        return _get_job_results_grouped_by_target(db, query_args)
    if query_args.group_by == "source":
        return _get_job_results_grouped_by_source(db, query_args)
    if query_args.group_by == "domain":
        return _get_job_results_grouped_by_domain(db, query_args)

    query = db.query(ExternalLink).filter(ExternalLink.job_id == query_args.job_id)
    query = apply_job_result_filters(
        query, search=query_args.search, exclude=query_args.exclude, status_filter=query_args.status_filter
    )
    return _get_job_results_no_grouping(query, query_args)


def get_results_summary(  # pylint: disable=too-many-locals
    db: DBSession, job_id: str, user_id: str, exclude: str | None = None, group_by: str = "none"
) -> dict[str, object]:
    """
    取得任務結果的統計摘要。

    Args:
        db (DBSession): Crawler DB Session。
        job_id (str): 任務 ID。
        user_id (str): 請求查詢的使用者 ID。
        exclude (str | None): 要排除的目標網域。
        group_by (str): 聚合方式。

    Returns:
        dict[str, object]: 統計摘要字典。

    Raises:
        ValueError: 找不到任務或無權限存取時拋出。
    """
    # pylint: disable=duplicate-code
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if (job.user_id or "") != (user_id or ""):
        raise ValueError("無權限存取此任務。")

    is_grouped = group_by and group_by not in ("none", "")

    if group_by == "target":
        key_col: InstrumentedAttribute = ExternalLink.target_url
    elif group_by == "source":
        key_col = ExternalLink.source_url
    elif group_by == "domain":
        key_col = ExternalLink.target_domain
    else:
        key_col = ExternalLink.id

    count_expr = count(key_col.distinct()) if is_grouped else count(key_col)
    insecure_expr = case(
        (
            and_(
                ExternalLink.is_secure == False,  # pylint: disable=singleton-comparison  # noqa: E712
                ExternalLink.status_category != "pending",
            ),
            key_col,
        ),
        else_=None,
    )
    insecure_count_expr = count(insecure_expr.distinct()) if is_grouped else count(insecure_expr)

    query: Query = db.query(
        ExternalLink.status_category,
        count_expr.label("cnt"),
        insecure_count_expr.label("insecure_cnt"),
    ).filter(ExternalLink.job_id == job_id)
    query = apply_job_result_filters(query, exclude=exclude)
    rows = query.group_by(ExternalLink.status_category).all()

    total_external = 0
    insecure_count = 0
    stats = {
        k: 0
        for k in ["dns_failed", "not_found", "server_error", "connection_error", "other_error", "blocked", "healthy"]
    }

    for row in rows:
        cat = row.status_category
        cnt = int(row.cnt)
        if not is_grouped:
            total_external += cnt
            insecure_count += int(row.insecure_cnt)

        if cat in stats:
            stats[cat] = cnt

    if is_grouped:
        total_query: Query = db.query(
            count_expr.label("total"),
            insecure_count_expr.label("insecure_cnt"),
        ).filter(ExternalLink.job_id == job_id)
        total_query = apply_job_result_filters(total_query, exclude=exclude)
        total_row = total_query.first()
        if total_row:
            total_external = int(total_row.total)
            insecure_count = int(total_row.insecure_cnt)

    return {
        "job_id": job_id,
        "total_external_links": total_external,
        "healthy_count": stats["healthy"],
        "dns_failed_count": stats["dns_failed"],
        "not_found_count": stats["not_found"],
        "server_error_count": stats["server_error"],
        "connection_error_count": stats["connection_error"],
        "other_error_count": stats["other_error"],
        "blocked_count": stats["blocked"],
        "insecure_count": insecure_count,
    }


def get_job_diff(
    db: DBSession,
    base_job_id: str,
    compare_job_id: str,
    user_id: str,
    exclude: str | None = None,
) -> dict[str, object]:
    """
    向下相容的比對兩個任務的外部連結差異轉呼叫函式。
    """
    from backend.jobs.services.diff import get_job_diff as diff_get_job_diff  # pylint: disable=import-outside-toplevel

    return diff_get_job_diff(
        db=db,
        base_job_id=base_job_id,
        compare_job_id=compare_job_id,
        user_id=user_id,
        exclude=exclude,
        scope="external",
    )


def _stream_no_grouping(cursor) -> Iterator[dict[str, object]]:
    """
    不進行分組，直接將結果串流輸出。

    Args:
        cursor (Iterator[ExternalLink]): 資料庫查詢結果的產生器。

    Yields:
        dict[str, object]: 單筆結果資料字典。
    """
    for lnk in cursor:
        yield {
            "source_url": lnk.source_url,
            "target_url": lnk.target_url,
            "ip_address": lnk.ip_address,
            "is_secure": lnk.is_secure,
            "http_status_code": lnk.http_status_code,
            "error_message": lnk.error_message,
            "created_at": lnk.created_at.isoformat(),
        }


def _stream_group_by_target(cursor) -> Iterator[Mapping[str, object]]:
    """
    依照目標網址進行分組，將結果串流輸出。

    Args:
        cursor (Iterator[ExternalLink]): 資料庫查詢結果的產生器。

    Yields:
        dict[str, object]: 單筆結果資料字典。
    """
    _SetStr2 = set[str]
    agg: defaultdict[str, dict[str, str | bool | int | _SetStr2 | None]] = defaultdict(
        lambda: {
            "target_url": "",
            "ip_address": None,
            "is_secure": True,
            "http_status_code": None,
            "error_message": None,
            "occurrence_count": 0,
            "source_urls": set(),
        }
    )
    for lnk in cursor:
        d = agg[lnk.target_url]
        d["target_url"] = lnk.target_url
        cnt = d["occurrence_count"]
        d["occurrence_count"] = (cnt if isinstance(cnt, int) else 0) + 1
        src_urls = d["source_urls"]
        if isinstance(src_urls, set):
            src_urls.add(lnk.source_url)
        d["is_secure"] = d["is_secure"] and lnk.is_secure
        if not d["ip_address"] and lnk.ip_address:
            d["ip_address"] = lnk.ip_address
        if d["http_status_code"] is None and lnk.http_status_code is not None:
            d["http_status_code"] = lnk.http_status_code
        if not d["error_message"] and lnk.error_message:
            d["error_message"] = lnk.error_message
    for v in agg.values():
        yield {
            "target_url": v["target_url"],
            "ip_address": v["ip_address"],
            "is_secure": v["is_secure"],
            "http_status_code": v["http_status_code"],
            "error_message": v["error_message"],
            "occurrence_count": v["occurrence_count"],
            "source_urls": sorted(list(v["source_urls"]) if isinstance(v["source_urls"], set) else []),
        }


def _stream_group_by_domain(cursor) -> Iterator[Mapping[str, object]]:
    """
    依照目標網域進行分組，將結果串流輸出。

    Args:
        cursor (Iterator[ExternalLink]): 資料庫查詢結果的產生器。

    Yields:
        dict[str, object]: 單筆結果資料字典。
    """
    _SetStr3 = set[str]
    agg: defaultdict[str, dict[str, str | int | _SetStr3]] = defaultdict(
        lambda: {"domain": "", "occurrence_count": 0, "unique_urls": set(), "source_urls": set()}
    )
    for lnk in cursor:
        dom = get_domain(lnk.target_url) or "unknown"
        d = agg[dom]
        d["domain"] = dom
        cnt2 = d["occurrence_count"]
        d["occurrence_count"] = (cnt2 if isinstance(cnt2, int) else 0) + 1
        unique_urls = d["unique_urls"]
        if isinstance(unique_urls, set):
            unique_urls.add(lnk.target_url)
        src_urls2 = d["source_urls"]
        if isinstance(src_urls2, set):
            src_urls2.add(lnk.source_url)

    result = []
    for v in agg.values():
        result.append(
            {
                "domain": v["domain"],
                "occurrence_count": v["occurrence_count"],
                "unique_urls_count": len(v["unique_urls"]) if isinstance(v["unique_urls"], set) else 0,
                "unique_urls": sorted(list(v["unique_urls"]) if isinstance(v["unique_urls"], set) else []),
                "source_urls": sorted(list(v["source_urls"]) if isinstance(v["source_urls"], set) else []),
            }
        )
    result.sort(key=lambda x: x["occurrence_count"] if isinstance(x["occurrence_count"], int) else 0, reverse=True)
    yield from result


def _stream_group_by_source(cursor) -> Iterator[Mapping[str, object]]:
    """
    依照來源網址進行分組，將結果串流輸出。

    Args:
        cursor (Iterator[ExternalLink]): 資料庫查詢結果的產生器。

    Yields:
        dict[str, object]: 單筆結果資料字典。
    """
    _ListDict = list[dict[str, object]]
    agg: defaultdict[str, dict[str, str | int | _ListDict]] = defaultdict(
        lambda: {"source_url": "", "occurrence_count": 0, "targets": []}
    )
    for lnk in cursor:
        d = agg[lnk.source_url]
        d["source_url"] = lnk.source_url
        cnt3 = d["occurrence_count"]
        d["occurrence_count"] = (cnt3 if isinstance(cnt3, int) else 0) + 1
        status_str = (
            str(lnk.http_status_code)
            if lnk.http_status_code is not None
            else ("DNS Failed" if not lnk.ip_address else "Error")
        )
        targets = d["targets"]
        if isinstance(targets, list):
            targets.append(
                {
                    "url": lnk.target_url,
                    "status": status_str,
                    "is_secure": lnk.is_secure,
                    "error_message": lnk.error_message,
                }
            )
    yield from agg.values()


def stream_job_results(db: DBSession, query_args: JobResultQuery) -> Iterator[Mapping[str, object]]:
    """
    查詢任務的外連結果，並以 yield 串流回傳以節省記憶體。

    Args:
        db (DBSession): Crawler DB Session。
        query_args (JobResultQuery): 結果查詢參數。

    Yields:
        dict[str, object]: 單筆結果資料字典。

    Raises:
        ValueError: 無權限存取此任務。
    """
    # pylint: disable=duplicate-code
    job = db.query(Job).filter(Job.id == query_args.job_id).first()
    if not job or (job.user_id or "") != (query_args.user_id or ""):
        raise ValueError("無權限存取此任務。")

    query = db.query(ExternalLink).filter(ExternalLink.job_id == query_args.job_id)
    query = apply_job_result_filters(
        query, search=query_args.search, exclude=query_args.exclude, status_filter=query_args.status_filter
    )

    # 使用 yield_per 每次只載入 2000 筆，避免 OOM
    cursor = query.order_by(ExternalLink.created_at).yield_per(2000)

    if query_args.group_by == "target":
        yield from _stream_group_by_target(cursor)
    elif query_args.group_by == "domain":
        yield from _stream_group_by_domain(cursor)
    elif query_args.group_by == "source":
        yield from _stream_group_by_source(cursor)
    else:
        yield from _stream_no_grouping(cursor)
