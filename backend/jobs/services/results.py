# pylint: disable=too-many-lines
"""
任務結果與統計查詢邏輯。
"""

import json
import logging
from collections import defaultdict
from collections.abc import Iterator

from sqlalchemy import Integer, String, asc, case, cast, desc
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.sql.functions import count
from sqlalchemy.sql.functions import max as sql_max
from sqlalchemy.sql.functions import min as sql_min
from sqlalchemy.sql.functions import sum as sql_sum

from backend.jobs.schemas import InternalResultQuery, JobResultQuery
from crawler.models import CrawlQueue, ExternalLink, Job, apply_job_result_filters
from crawler.utils import JSONGroupArray, JSONObject, format_crawl_queue_item, get_domain

logger: logging.Logger = logging.getLogger(__name__)

ERROR_STATUS_FILTERS = [
    "not_found",
    "server_error",
    "connection_error",
    "other_error",
    "blocked",
    "insecure",
]


def _parse_json_list(val: object) -> list:
    """
    解析 JSON 字串為列表，用於反序列化資料庫聚合的 JSON 陣列。

    Args:
        val (object): 參數說明。

    Returns:
        list: 回傳說明。
    """
    if isinstance(val, str):
        try:
            return json.loads(val) or []
        except json.JSONDecodeError:
            return []
    return list(val) if val else []


def _apply_col_filters(
    query: Query,
    col_filters_str: str | None,
    filter_map: dict[str, object],
    is_having: bool = False,
) -> Query:
    """
    動態套用欄位過濾器，減少主函式的區域變數與複雜度。

    Args:
        query (Query): 參數說明。
        col_filters_str (object): 參數說明。
        filter_map (object): 參數說明。
        is_having (bool): 參數說明。

    Returns:
        Query: 回傳說明。
    """
    if not col_filters_str:
        return query
    try:
        filters = json.loads(col_filters_str)
        for k, v in filters.items():
            if v and k in filter_map:
                cond = filter_map[k](str(v).lower())
                query = query.having(cond) if is_having else query.filter(cond)
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return query


def _apply_sorting(
    query: Query,
    sort_by: str | None,
    sort_asc: bool,
    sort_map: dict[str, object],
    default_sort: object,
) -> Query:
    """
    動態套用排序規則，減少主函式的區域變數與複雜度。

    Args:
        query (Query): 參數說明。
        sort_by (object): 參數說明。
        sort_asc (bool): 參數說明。
        sort_map (object): 參數說明。
        default_sort (object): 參數說明。

    Returns:
        Query: 回傳說明。
    """
    if sort_by and sort_by in sort_map:
        order_func = asc if sort_asc else desc
        return query.order_by(order_func(sort_map[sort_by]))
    return query.order_by(default_sort)


def _get_job_results_grouped_by_target(
    db: DBSession,
    query_args: JobResultQuery,
) -> dict[str, object]:
    """
    查詢任務的外連結果，並依目標網址 (Target URL) 聚合。

    Args:
        db (DBSession): 參數說明。
        query_args (JobResultQuery): 參數說明。

    Returns:
        object: 回傳說明。
    """
    # 1. 建立基礎查詢，取得目標網址與來源網址的對應關係
    base_q = db.query(ExternalLink.target_url, ExternalLink.source_url).filter(ExternalLink.job_id == query_args.job_id)
    base_q = apply_job_result_filters(
        base_q, search=query_args.search, exclude=query_args.exclude, status_filter=query_args.status_filter
    )
    # 2. 建立子查詢，過濾出不重複的目標與來源網址組合
    distinct_sources = base_q.distinct().subquery("distinct_sources")

    # 3. 建立子查詢，將不重複的來源網址按目標網址聚合成 JSON 陣列
    sources_agg = (
        db.query(distinct_sources.c.target_url, JSONGroupArray(distinct_sources.c.source_url).label("source_urls"))
        .group_by(distinct_sources.c.target_url)
        .subquery("sources_agg")
    )

    # 4. 建立子查詢，計算各目標網址的統計數據（如 IP、HTTP 狀態、發生次數等）
    target_stats = db.query(
        ExternalLink.target_url,
        sql_max(ExternalLink.ip_address).label("ip_address"),
        sql_min(cast(ExternalLink.is_secure, Integer)).label("is_secure"),
        sql_max(ExternalLink.http_status_code).label("http_status_code"),
        sql_max(ExternalLink.error_message).label("error_message"),
        count(ExternalLink.id).label("occurrence_count"),
    ).filter(ExternalLink.job_id == query_args.job_id)
    target_stats = apply_job_result_filters(
        target_stats, search=query_args.search, exclude=query_args.exclude, status_filter=query_args.status_filter
    )
    target_stats = target_stats.group_by(ExternalLink.target_url).subquery("target_stats")

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
    main_q = _apply_col_filters(main_q, query_args.col_filters, filter_map)

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
    main_q = _apply_sorting(
        main_q,
        query_args.sort_by,
        query_args.sort_asc,
        sort_map,
        desc(target_stats.c.occurrence_count),
    )

    # 8. 執行分頁查詢
    total = main_q.count()
    items_list = []
    for row in main_q.offset((query_args.page - 1) * query_args.page_size).limit(query_args.page_size).all():
        items_list.append(
            {
                "target_url": row[0],
                "ip_address": row[1],
                "is_secure": bool(row[2]),
                "http_status_code": row[3],
                "error_message": row[4],
                "occurrence_count": row[5],
                "source_urls": sorted(_parse_json_list(row[6]))[:10],
            }
        )

    return {
        "items": items_list,
        "total": total,
        "page": query_args.page,
        "page_size": query_args.page_size,
        "total_pages": (total + query_args.page_size - 1) // query_args.page_size if total > 0 else 1,
    }


def _get_job_results_grouped_by_source(
    db: DBSession,
    query_args: JobResultQuery,
) -> dict[str, object]:
    """
    查詢任務的外連結果，並依來源網頁 (Source URL) 聚合。

    Args:
        db (DBSession): 參數說明。
        query_args (JobResultQuery): 參數說明。

    Returns:
        object: 回傳說明。
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
    main_q = _apply_col_filters(main_q, query_args.col_filters, filter_map, is_having=True)

    # 4. 動態套用排序規則
    sort_map = {
        "source_url": ExternalLink.source_url,
        "occurrence_count": count(ExternalLink.id),
        "targets": cast(JSONGroupArray(target_obj), String),
    }
    main_q = _apply_sorting(
        main_q,
        query_args.sort_by,
        query_args.sort_asc,
        sort_map,
        desc(count(ExternalLink.id)),
    )

    # 5. 執行分頁查詢
    total = main_q.count()
    offset = (query_args.page - 1) * query_args.page_size
    results = main_q.offset(offset).limit(query_args.page_size).all()

    items_list = []
    for row in results:
        targets = row[2]
        if isinstance(targets, str):
            try:
                targets = json.loads(targets)
            except json.JSONDecodeError:
                targets = []

        items_list.append(
            {
                "source_url": row[0],
                "occurrence_count": row[1],
                "targets": targets[:10],
            }
        )

    total_pages = (total + query_args.page_size - 1) // query_args.page_size if total > 0 else 1
    return {
        "items": items_list,
        "total": total,
        "page": query_args.page,
        "page_size": query_args.page_size,
        "total_pages": total_pages,
    }


def _get_job_results_grouped_by_domain(
    db: DBSession,
    query_args: JobResultQuery,
) -> dict[str, object]:
    """
    查詢任務的外連結果，並依外部網域 (Domain) 聚合。

    Args:
        db (DBSession): 參數說明。
        query_args (JobResultQuery): 參數說明。

    Returns:
        object: 回傳說明。
    """
    # 1. 建立基礎查詢，提取目標網域、目標網址與來源網址的關係
    base_q = db.query(ExternalLink.target_domain, ExternalLink.target_url, ExternalLink.source_url).filter(
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
    main_q = _apply_col_filters(main_q, query_args.col_filters, filter_map)

    # 7. 動態套用排序規則
    sort_map = {
        "domain": domain_stats.c.target_domain,
        "occurrence_count": domain_stats.c.occurrence_count,
        "unique_urls_count": urls_agg.c.unique_urls_count,
        "unique_urls": cast(urls_agg.c.unique_urls, String),
        "source_urls": cast(sources_agg.c.source_urls, String),
    }
    main_q = _apply_sorting(
        main_q,
        query_args.sort_by,
        query_args.sort_asc,
        sort_map,
        desc(domain_stats.c.occurrence_count),
    )

    # 8. 執行分頁查詢
    total = main_q.count()
    items_list = []
    for row in main_q.offset((query_args.page - 1) * query_args.page_size).limit(query_args.page_size).all():
        items_list.append(
            {
                "domain": row[0] or "unknown",
                "occurrence_count": row[1],
                "unique_urls_count": row[2] or 0,
                "unique_urls": sorted(_parse_json_list(row[3]))[:10],
                "source_urls": sorted(_parse_json_list(row[4]))[:10],
            }
        )

    return {
        "items": items_list,
        "total": total,
        "page": query_args.page,
        "page_size": query_args.page_size,
        "total_pages": (total + query_args.page_size - 1) // query_args.page_size if total > 0 else 1,
    }


def _get_job_results_no_grouping(
    query: Query,
    query_args: JobResultQuery,
) -> dict[str, object]:
    """
    查詢任務的外連結果，無聚合模式。

    Args:
        query (Query): 參數說明。
        query_args (JobResultQuery): 參數說明。

    Returns:
        object: 回傳說明。
    """
    filter_map = {
        "target_url": lambda v: ExternalLink.target_url.ilike(f"%{v}%"),
        "source_url": lambda v: ExternalLink.source_url.ilike(f"%{v}%"),
        "ip_address": lambda v: ExternalLink.ip_address.ilike(f"%{v}%"),
        "is_secure": lambda v: ExternalLink.is_secure.is_(v in ("true", "1", "yes", "✓", "v", "t")),
        "http_status_code": lambda v: cast(ExternalLink.http_status_code, String).ilike(f"%{v}%"),
        "error_message": lambda v: ExternalLink.error_message.ilike(f"%{v}%"),
    }
    query = _apply_col_filters(query, query_args.col_filters, filter_map)

    sort_map = {
        "target_url": ExternalLink.target_url,
        "source_url": ExternalLink.source_url,
        "ip_address": ExternalLink.ip_address,
        "is_secure": ExternalLink.is_secure,
        "http_status_code": ExternalLink.http_status_code,
        "error_message": ExternalLink.error_message,
    }
    query = _apply_sorting(
        query,
        query_args.sort_by,
        query_args.sort_asc,
        sort_map,
        ExternalLink.created_at,
    )

    total = query.count()
    offset = (query_args.page - 1) * query_args.page_size
    links = query.offset(offset).limit(query_args.page_size).all()
    items_list = [
        {
            "id": lnk.id,
            "source_url": lnk.source_url,
            "target_url": lnk.target_url,
            "ip_address": lnk.ip_address,
            "is_secure": lnk.is_secure,
            "http_status_code": lnk.http_status_code,
            "error_message": lnk.error_message,
            "created_at": lnk.created_at.isoformat(),
        }
        for lnk in links
    ]
    total_pages = (total + query_args.page_size - 1) // query_args.page_size if total > 0 else 1
    return {
        "items": items_list,
        "total": total,
        "page": query_args.page,
        "page_size": query_args.page_size,
        "total_pages": total_pages,
    }


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
    job = db.query(Job).filter(Job.id == query_args.job_id).first()
    if not job:
        raise ValueError(f"找不到任務 ID: {query_args.job_id}")
    if job.user_id != query_args.user_id:
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


def _classify_link_status(lnk: ExternalLink) -> tuple[bool, bool, bool, bool, bool, bool, bool, bool]:
    """
    分類外連的狀態。

    Args:
        lnk (ExternalLink): 參數說明。

    Returns:
        object: 回傳說明。
    """
    is_dns_failed = not lnk.ip_address
    c = lnk.http_status_code
    is_blocked = c in (401, 403, 405, 406, 429)
    is_insecure = not lnk.is_secure
    is_healthy = bool(lnk.ip_address) and c is not None and c < 400

    is_not_found = c in (404, 410)
    is_server_error = c is not None and 500 <= c < 600
    is_connection_error = c is None and bool(lnk.ip_address)
    is_other_error = c is not None and ((400 <= c < 500 and not is_blocked and not is_not_found) or c >= 600)

    return (
        is_dns_failed,
        is_not_found,
        is_server_error,
        is_connection_error,
        is_other_error,
        is_blocked,
        is_insecure,
        is_healthy,
    )


def _get_grouped_results_summary(query: Query, group_by: str) -> dict[str, int]:
    """
    計算分組後的聚合統計結果。

    Args:
        query (Query): SQLAlchemy 查詢物件。
        group_by (str): 分組依據。

    Returns:
        dict[str, int]: 包含 total, healthy_count, dns_failed_count, http_error_count, insecure_count 的統計結果。
    """
    sets = defaultdict(set)
    status_keys = (
        "dns_failed",
        "not_found",
        "server_error",
        "connection_error",
        "other_error",
        "blocked",
        "insecure",
        "healthy_count",
    )

    if group_by == "target":

        def key_func(lnk: ExternalLink) -> str:
            return lnk.target_url

    elif group_by == "source":

        def key_func(lnk: ExternalLink) -> str:
            return lnk.source_url

    elif group_by == "domain":

        def key_func(lnk: ExternalLink) -> str:
            return get_domain(lnk.target_url) or "unknown"

    else:

        def key_func(lnk: ExternalLink) -> object:
            return lnk.id

    for lnk in query.yield_per(2000):
        key = key_func(lnk)
        sets["all"].add(key)

        statuses = _classify_link_status(lnk)
        for status_name, is_active in zip(status_keys, statuses):
            if is_active:
                sets[status_name].add(key)

    return {
        "total_external": len(sets["all"]),
        "dns_failed": len(sets["dns_failed"]),
        "not_found": len(sets["not_found"]),
        "server_error": len(sets["server_error"]),
        "connection_error": len(sets["connection_error"]),
        "other_error": len(sets["other_error"]),
        "blocked": len(sets["blocked"]),
        "insecure": len(sets["insecure"]),
        "healthy_count": len(sets["healthy_count"]),
    }


def _get_results_summary_no_grouping(db: DBSession, job_id: str, exclude: str | None = None) -> dict[str, int]:
    """
    計算無分組下的外連結果統計摘要。

    Args:
        db (DBSession): 參數說明。
        job_id (str): 參數說明。
        exclude (object): 參數說明。

    Returns:
        object: 回傳說明。
    """
    # 透過單次聚合查詢大幅減少資料庫 I/O，優化百萬級外連任務的報表讀取效能
    query = db.query(
        count(ExternalLink.id).label("total"),
        sql_sum(
            case(
                (
                    (ExternalLink.ip_address.is_(None)) | (ExternalLink.ip_address == ""),
                    1,
                ),
                else_=0,
            )
        ).label("dns_failed"),
        sql_sum(case((ExternalLink.http_status_code.in_([404, 410]), 1), else_=0)).label("not_found"),
        sql_sum(
            case(((ExternalLink.http_status_code >= 500) & (ExternalLink.http_status_code < 600), 1), else_=0)
        ).label("server_error"),
        sql_sum(
            case(
                (
                    (ExternalLink.http_status_code.is_(None))
                    & (ExternalLink.ip_address.isnot(None))
                    & (ExternalLink.ip_address != ""),
                    1,
                ),
                else_=0,
            )
        ).label("connection_error"),
        sql_sum(
            case(
                (
                    (
                        (ExternalLink.http_status_code >= 400)
                        & (ExternalLink.http_status_code < 500)
                        & (~ExternalLink.http_status_code.in_([404, 410, 401, 403, 405, 406, 429]))
                    )
                    | (ExternalLink.http_status_code >= 600),
                    1,
                ),
                else_=0,
            )
        ).label("other_error"),
        sql_sum(case((ExternalLink.http_status_code.in_([401, 403, 405, 406, 429]), 1), else_=0)).label("blocked"),
        sql_sum(case((ExternalLink.is_secure.is_(False), 1), else_=0)).label("insecure"),
    ).filter(ExternalLink.job_id == job_id)

    query = apply_job_result_filters(query, exclude=exclude)

    stats = query.first()

    total_external = int(stats.total) if stats and stats.total else 0
    dns_failed = int(stats.dns_failed) if stats and stats.dns_failed else 0
    not_found = int(stats.not_found) if stats and stats.not_found else 0
    server_error = int(stats.server_error) if stats and stats.server_error else 0
    connection_error = int(stats.connection_error) if stats and stats.connection_error else 0
    other_error = int(stats.other_error) if stats and stats.other_error else 0
    blocked = int(stats.blocked) if stats and stats.blocked else 0
    insecure = int(stats.insecure) if stats and stats.insecure else 0

    healthy_count = total_external - dns_failed - not_found - server_error - connection_error - other_error - blocked

    return {
        "total_external": total_external,
        "dns_failed": dns_failed,
        "not_found": not_found,
        "server_error": server_error,
        "connection_error": connection_error,
        "other_error": other_error,
        "blocked": blocked,
        "insecure": insecure,
        "healthy_count": healthy_count,
    }


def _get_results_summary_grouped(db: DBSession, job_id: str, exclude: str | None, group_by: str) -> dict[str, int]:
    """
    計算分組聚合下的外連結果統計摘要。

    Args:
        db (DBSession): 參數說明。
        job_id (str): 參數說明。
        exclude (object): 參數說明。
        group_by (str): 參數說明。

    Returns:
        object: 回傳說明。
    """
    query = db.query(ExternalLink).filter(ExternalLink.job_id == job_id)
    query = apply_job_result_filters(query, exclude=exclude)
    stats_dict = _get_grouped_results_summary(query, group_by)
    return {
        "total_external": stats_dict["total_external"],
        "dns_failed": stats_dict["dns_failed"],
        "not_found": stats_dict["not_found"],
        "server_error": stats_dict["server_error"],
        "connection_error": stats_dict["connection_error"],
        "other_error": stats_dict["other_error"],
        "blocked": stats_dict["blocked"],
        "insecure": stats_dict["insecure"],
        "healthy_count": stats_dict["healthy_count"],
    }


def get_results_summary(
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
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if job.user_id != user_id:
        raise ValueError("無權限存取此任務。")

    total_queue = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).count()

    if group_by == "none":
        stats = _get_results_summary_no_grouping(db, job_id, exclude)
    else:
        stats = _get_results_summary_grouped(db, job_id, exclude, group_by)

    return {
        "job_id": job_id,
        "total_crawled_pages": total_queue,
        "total_external_links": stats["total_external"],
        "healthy_count": stats["healthy_count"],
        "dns_failed_count": stats["dns_failed"],
        "not_found_count": stats["not_found"],
        "server_error_count": stats["server_error"],
        "connection_error_count": stats["connection_error"],
        "other_error_count": stats["other_error"],
        "blocked_count": stats["blocked"],
        "insecure_count": stats["insecure"],
    }


def _build_target_dict_for_diff(db: DBSession, job_id: str, exclude: str | None = None) -> dict[str, dict[str, object]]:
    """
    為指定任務建立目標網址的聚合字典，以供 Diff 比對使用。

    Args:
        db (DBSession): Crawler DB Session。
        job_id (str): 任務 ID。
        exclude (str | None): 要排除的目標網域。

    Returns:
        dict[str, dict[str, object]]: 聚合後的外連字典。
    """
    agg: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "ip": None,
            "is_secure": True,
            "status_code": None,
            "error": None,
            "sources": set(),
        }
    )
    query = db.query(ExternalLink).filter(ExternalLink.job_id == job_id)

    if exclude:
        excludes = [e.strip() for e in exclude.split(",") if e.strip()]
        for exc in excludes:
            query = query.filter(~ExternalLink.target_url.ilike(f"%{exc}%"))

    cursor = query.yield_per(2000)
    for lnk in cursor:
        d = agg[lnk.target_url]
        d["sources"].add(lnk.source_url)
        d["is_secure"] = d["is_secure"] and lnk.is_secure
        if not d["ip"] and lnk.ip_address:
            d["ip"] = lnk.ip_address
        if d["status_code"] is None and lnk.http_status_code is not None:
            d["status_code"] = lnk.http_status_code
        if not d["error"] and lnk.error_message:
            d["error"] = lnk.error_message
    return dict(agg)


def _is_bad_link(item: dict[str, object]) -> bool:
    """
    判斷給定的外連項目是否處於異常/失效狀態。

    Args:
        item (dict[str, object]): 外連項目的字典資料。

    Returns:
        bool: 若為異常/失效連結則回傳 True，否則回傳 False。
    """
    if not item["ip"]:
        return True
    status_code = item["status_code"]
    if status_code is not None and int(str(status_code)) >= 400:
        return True
    if item["error"]:
        return True
    return False


def _process_diff_common_url(
    url: str, item_a: dict[str, object], item_b: dict[str, object], diff_lists: dict[str, list[dict[str, object]]]
) -> None:
    """
    處理兩個任務中皆存在的外連網址，比較差異並加入對應的結果清單中。

    Args:
        url (str): 目標網址。
        item_a (dict[str, object]): 舊任務的外連項目資料。
        item_b (dict[str, object]): 新任務的外連項目資料。
        diff_lists (dict[str, list[dict[str, object]]]): 存放差異結果的字典。

    Returns:
        None
    """
    if item_a["ip"] and item_b["ip"] and item_a["ip"] != item_b["ip"]:
        diff_lists["ip_changed"].append(
            {
                "target_url": url,
                "old_ip": item_a["ip"],
                "new_ip": item_b["ip"],
                "sources": sorted(list(item_b["sources"])[:10]),
            }
        )
    if item_a["is_secure"] and not item_b["is_secure"]:
        diff_lists["security_downgraded"].append({"target_url": url, "sources": sorted(list(item_b["sources"])[:10])})

    a_bad = _is_bad_link(item_a)
    b_bad = _is_bad_link(item_b)

    if not a_bad and b_bad:
        diff_lists["degraded"].append(
            {
                "target_url": url,
                "old_status": item_a["status_code"],
                "old_error": item_a["error"],
                "new_status": item_b["status_code"],
                "new_error": item_b["error"],
                "sources": sorted(list(item_b["sources"])[:10]),
            }
        )
    elif a_bad and not b_bad:
        diff_lists["recovered"].append(
            {
                "target_url": url,
                "old_status": item_a["status_code"],
                "old_error": item_a["error"],
                "new_status": item_b["status_code"],
                "new_error": item_b["error"],
                "sources": sorted(list(item_b["sources"])[:10]),
            }
        )


def get_job_diff(
    db: DBSession,
    base_job_id: str,
    compare_job_id: str,
    user_id: str,
    exclude: str | None = None,
) -> dict[str, object]:
    """
    比對兩個任務的外部連結差異 (支援排除網域)。

    Args:
        db (DBSession): Crawler DB Session。
        base_job_id (str): 基準任務 ID (舊)。
        compare_job_id (str): 對照任務 ID (新)。
        user_id (str): 請求查詢的使用者 ID。
        exclude (str | None): 要排除的目標網域。

    Returns:
        dict[str, object]: 差異比對結果字典。

    Raises:
        ValueError: 找不到任務或無權限存取時拋出。
    """
    job_a = db.query(Job).filter(Job.id == base_job_id).first()
    job_b = db.query(Job).filter(Job.id == compare_job_id).first()

    if not job_a or job_a.user_id != user_id:
        raise ValueError(f"找不到基準任務 ID: {base_job_id}")
    if not job_b or job_b.user_id != user_id:
        raise ValueError(f"找不到對照任務 ID: {compare_job_id}")

    dict_a = _build_target_dict_for_diff(db, base_job_id, exclude)
    dict_b = _build_target_dict_for_diff(db, compare_job_id, exclude)

    set_a = set(dict_a.keys())
    set_b = set(dict_b.keys())

    diff_lists: dict[str, list[dict[str, object]]] = {
        "ip_changed": [],
        "degraded": [],
        "security_downgraded": [],
        "recovered": [],
    }

    for url in set_a & set_b:
        _process_diff_common_url(url, dict_a[url], dict_b[url], diff_lists)

    new_links = [
        {
            "target_url": url,
            "ip": dict_b[url]["ip"],
            "status_code": dict_b[url]["status_code"],
            "error": dict_b[url]["error"],
            "sources": sorted(list(dict_b[url]["sources"])[:10]),
        }
        for url in (set_b - set_a)
    ]

    removed_links = [
        {
            "target_url": url,
            "old_ip": dict_a[url]["ip"],
            "old_status_code": dict_a[url]["status_code"],
            "old_error": dict_a[url]["error"],
            "sources": sorted(list(dict_a[url]["sources"])[:10]),
        }
        for url in (set_a - set_b)
    ]

    return {
        "base_job": {"id": job_a.id, "created_at": job_a.created_at.isoformat()},
        "compare_job": {"id": job_b.id, "created_at": job_b.created_at.isoformat()},
        "summary": {
            "ip_changed": len(diff_lists["ip_changed"]),
            "degraded": len(diff_lists["degraded"]),
            "security_downgraded": len(diff_lists["security_downgraded"]),
            "new_links": len(new_links),
            "removed_links": len(removed_links),
            "recovered": len(diff_lists["recovered"]),
        },
        "details": {
            "ip_changed": diff_lists["ip_changed"],
            "degraded": diff_lists["degraded"],
            "security_downgraded": diff_lists["security_downgraded"],
            "new_links": new_links,
            "removed_links": removed_links,
            "recovered": diff_lists["recovered"],
        },
    }


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


def _stream_group_by_target(cursor) -> Iterator[dict[str, object]]:
    """
    依照目標網址進行分組，將結果串流輸出。

    Args:
        cursor (Iterator[ExternalLink]): 資料庫查詢結果的產生器。

    Yields:
        dict[str, object]: 單筆結果資料字典。
    """
    agg = defaultdict(
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
        d["occurrence_count"] += 1
        d["source_urls"].add(lnk.source_url)
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
            "source_urls": sorted(list(v["source_urls"])),
        }


def _stream_group_by_domain(cursor) -> Iterator[dict[str, object]]:
    """
    依照目標網域進行分組，將結果串流輸出。

    Args:
        cursor (Iterator[ExternalLink]): 資料庫查詢結果的產生器。

    Yields:
        dict[str, object]: 單筆結果資料字典。
    """
    agg = defaultdict(lambda: {"domain": "", "occurrence_count": 0, "unique_urls": set(), "source_urls": set()})
    for lnk in cursor:
        dom = get_domain(lnk.target_url) or "unknown"
        d = agg[dom]
        d["domain"] = dom
        d["occurrence_count"] += 1
        d["unique_urls"].add(lnk.target_url)
        d["source_urls"].add(lnk.source_url)

    result = []
    for v in agg.values():
        result.append(
            {
                "domain": v["domain"],
                "occurrence_count": v["occurrence_count"],
                "unique_urls_count": len(v["unique_urls"]),
                "unique_urls": sorted(list(v["unique_urls"])),
                "source_urls": sorted(list(v["source_urls"])),
            }
        )
    result.sort(key=lambda x: x["occurrence_count"], reverse=True)
    yield from result


def _stream_group_by_source(cursor) -> Iterator[dict[str, object]]:
    """
    依照來源網址進行分組，將結果串流輸出。

    Args:
        cursor (Iterator[ExternalLink]): 資料庫查詢結果的產生器。

    Yields:
        dict[str, object]: 單筆結果資料字典。
    """
    agg = defaultdict(lambda: {"source_url": "", "occurrence_count": 0, "targets": []})
    for lnk in cursor:
        d = agg[lnk.source_url]
        d["source_url"] = lnk.source_url
        d["occurrence_count"] += 1
        status_str = (
            str(lnk.http_status_code)
            if lnk.http_status_code is not None
            else ("DNS Failed" if not lnk.ip_address else "Error")
        )
        d["targets"].append(
            {
                "url": lnk.target_url,
                "status": status_str,
                "is_secure": lnk.is_secure,
                "error_message": lnk.error_message,
            }
        )
    yield from agg.values()


def stream_job_results(db: DBSession, query_args: JobResultQuery) -> Iterator[dict[str, object]]:
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
    job = db.query(Job).filter(Job.id == query_args.job_id).first()
    if not job or job.user_id != query_args.user_id:
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
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if job.user_id != user_id:
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
    job = db.query(Job).filter(Job.id == query_args.job_id).first()
    if not job or job.user_id != query_args.user_id:
        raise ValueError("無權限存取此任務。")

    query = db.query(CrawlQueue).filter(
        CrawlQueue.job_id == query_args.job_id,
        CrawlQueue.status.in_(["failed", "warning"]),
    )
    query = apply_internal_result_filters(query, query_args.status_filter)

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
        yield from results["items"]
    else:
        cursor = query.order_by(CrawlQueue.id).yield_per(2000)
        for q in cursor:
            yield format_crawl_queue_item(q)


def apply_internal_result_filters(query: Query, status_filter: str | None) -> Query:
    """
    套用內部失效連結的過濾條件。

    Args:
        query (Query): SQLAlchemy 查詢物件。
        status_filter (str | None): 狀態篩選條件。

    Returns:
        Query: 加上過濾條件後的 SQLAlchemy 查詢物件。
    """
    if not status_filter or status_filter == "all":
        return query

    if status_filter == "not_found":
        query = query.filter(CrawlQueue.status == "failed", CrawlQueue.status_code.in_([404, 410]))
    elif status_filter == "server_error":
        query = query.filter(CrawlQueue.status == "failed", CrawlQueue.status_code >= 500, CrawlQueue.status_code < 600)
    elif status_filter == "access_denied":
        query = query.filter(CrawlQueue.status == "failed", CrawlQueue.status_code.in_([401, 403]))
    elif status_filter == "timeout":
        query = query.filter(
            CrawlQueue.status == "failed",
            CrawlQueue.status_code.is_(None),
            (CrawlQueue.error_message.ilike("%timeout%")) | (CrawlQueue.error_message.ilike("%timed out%")),
        )
    elif status_filter == "connection_error":
        query = query.filter(
            CrawlQueue.status == "failed",
            CrawlQueue.status_code.is_(None),
            ~CrawlQueue.error_message.ilike("%timeout%"),
            ~CrawlQueue.error_message.ilike("%timed out%"),
        )
    elif status_filter == "warning":
        query = query.filter(CrawlQueue.status == "warning")
    elif status_filter == "other_error":
        query = query.filter(
            CrawlQueue.status == "failed",
            CrawlQueue.status_code.isnot(None),
            ~CrawlQueue.status_code.in_([404, 410, 401, 403]),
            (CrawlQueue.status_code < 500) | (CrawlQueue.status_code >= 600),
        )
    return query


def _get_internal_results_summary_none(db: DBSession, job_id: str) -> dict[str, int]:
    """
    計算無分組下的內部網頁失敗統計結果。

    Args:
        db (DBSession): 參數說明。
        job_id (str): 參數說明。

    Returns:
        object: 回傳說明。
    """
    query = db.query(
        count(CrawlQueue.id).label("total"),
        sql_sum(case((CrawlQueue.status_code.in_([404, 410]), 1), else_=0)).label("not_found"),
        sql_sum(case(((CrawlQueue.status_code >= 500) & (CrawlQueue.status_code < 600), 1), else_=0)).label(
            "server_error"
        ),
        sql_sum(case((CrawlQueue.status_code.in_([401, 403]), 1), else_=0)).label("access_denied"),
        sql_sum(
            case(
                (
                    (CrawlQueue.status == "failed")
                    & (CrawlQueue.status_code.is_(None))
                    & ((CrawlQueue.error_message.ilike("%timeout%")) | (CrawlQueue.error_message.ilike("%timed out%"))),
                    1,
                ),
                else_=0,
            )
        ).label("timeout"),
        sql_sum(
            case(
                (
                    (CrawlQueue.status == "failed")
                    & (CrawlQueue.status_code.is_(None))
                    & (~CrawlQueue.error_message.ilike("%timeout%"))
                    & (~CrawlQueue.error_message.ilike("%timed out%")),
                    1,
                ),
                else_=0,
            )
        ).label("connection_error"),
        sql_sum(case((CrawlQueue.status == "warning", 1), else_=0)).label("warning"),
    ).filter(CrawlQueue.job_id == job_id, CrawlQueue.status.in_(["failed", "warning"]))

    stats = query.first()
    total = int(stats.total) if stats and stats.total else 0
    not_found = int(stats.not_found) if stats and stats.not_found else 0
    server_error = int(stats.server_error) if stats and stats.server_error else 0
    access_denied = int(stats.access_denied) if stats and stats.access_denied else 0
    timeout = int(stats.timeout) if stats and stats.timeout else 0
    connection_error = int(stats.connection_error) if stats and stats.connection_error else 0
    warning = int(stats.warning) if stats and stats.warning else 0
    other_error = total - not_found - server_error - access_denied - timeout - connection_error - warning

    return {
        "total": total,
        "server_error": server_error,
        "connection_error": connection_error,
        "timeout": timeout,
        "not_found": not_found,
        "other_error": other_error,
        "warning": warning,
        "access_denied": access_denied,
    }


def _get_internal_results_summary_grouped(db: DBSession, job_id: str, group_by: str) -> dict[str, int]:
    """
    計算分組後的內部網頁失敗統計結果。

    Args:
        db (DBSession): 參數說明。
        job_id (str): 參數說明。
        group_by (str): 參數說明。

    Returns:
        object: 回傳說明。
    """
    sets = defaultdict(set)
    query = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.status.in_(["failed", "warning"]))

    if group_by == "source":

        def key_func(q: CrawlQueue) -> str:
            return q.source_url or ""

    else:

        def key_func(q: CrawlQueue) -> object:
            return q.id

    for q in query.yield_per(2000):
        key = key_func(q)
        sets["all"].add(key)

        c = q.status_code
        msg = str(q.error_message or "").lower()

        if q.status == "warning":
            sets["warning"].add(key)
        elif c in (404, 410):
            sets["not_found"].add(key)
        elif c is not None and 500 <= c < 600:
            sets["server_error"].add(key)
        elif c in (401, 403):
            sets["access_denied"].add(key)
        elif c is None and ("timeout" in msg or "timed out" in msg):
            sets["timeout"].add(key)
        elif c is None:
            sets["connection_error"].add(key)
        else:
            sets["other_error"].add(key)

    return {
        "total": len(sets["all"]),
        "server_error": len(sets["server_error"]),
        "connection_error": len(sets["connection_error"]),
        "timeout": len(sets["timeout"]),
        "not_found": len(sets["not_found"]),
        "other_error": len(sets["other_error"]),
        "warning": len(sets["warning"]),
        "access_denied": len(sets["access_denied"]),
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
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job or job.user_id != user_id:
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
        db (DBSession): 參數說明。
        query_args (InternalResultQuery): 參數說明。

    Returns:
        object: 回傳說明。
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
    ).filter(CrawlQueue.job_id == query_args.job_id, CrawlQueue.status.in_(["failed", "warning"]))

    main_q = apply_internal_result_filters(main_q, query_args.status_filter)
    main_q = main_q.group_by(CrawlQueue.source_url)

    # 3. 動態套用欄位過濾器
    filter_map = {
        "source_url": lambda v: CrawlQueue.source_url.ilike(f"%{v}%"),
        "occurrence_count": lambda v: cast(count(CrawlQueue.id), String).ilike(f"%{v}%"),
        "targets": lambda v: cast(JSONGroupArray(target_obj), String).ilike(f"%{v}%"),
    }
    main_q = _apply_col_filters(main_q, query_args.col_filters, filter_map, is_having=True)

    # 4. 動態套用排序規則
    sort_map = {
        "source_url": CrawlQueue.source_url,
        "occurrence_count": count(CrawlQueue.id),
        "targets": cast(JSONGroupArray(target_obj), String),
    }
    main_q = _apply_sorting(
        main_q,
        query_args.sort_by,
        query_args.sort_asc,
        sort_map,
        desc(count(CrawlQueue.id)),
    )

    # 5. 執行分頁查詢
    total = main_q.count()
    items_list = []
    offset = (query_args.page - 1) * query_args.page_size
    for row in main_q.offset(offset).limit(query_args.page_size).all():
        items_list.append(
            {
                "source_url": row[0] or "",
                "occurrence_count": row[1],
                "targets": _parse_json_list(row[2])[:10] if query_args.truncate_lists else _parse_json_list(row[2]),
            }
        )

    return {
        "items": items_list,
        "total": total,
        "page": query_args.page,
        "page_size": query_args.page_size,
        "total_pages": (total + query_args.page_size - 1) // query_args.page_size if total > 0 else 1,
    }


def _get_internal_errors_no_grouping(
    query: Query,
    query_args: InternalResultQuery,
) -> dict[str, object]:
    """
    取得任務內部網頁爬取失敗的紀錄列表，無聚合模式。

    Args:
        query (Query): 參數說明。
        query_args (InternalResultQuery): 參數說明。

    Returns:
        object: 回傳說明。
    """
    filter_map = {
        "URL": lambda v: CrawlQueue.url.ilike(f"%{v}%"),
        "Source URL": lambda v: CrawlQueue.source_url.ilike(f"%{v}%"),
        "HTTP Status Code": lambda v: cast(CrawlQueue.status_code, String).ilike(f"%{v}%"),
        "Error Message": lambda v: CrawlQueue.error_message.ilike(f"%{v}%"),
    }
    query = _apply_col_filters(query, query_args.col_filters, filter_map)

    sort_map = {
        "URL": CrawlQueue.url,
        "Source URL": CrawlQueue.source_url,
        "HTTP Status Code": CrawlQueue.status_code,
        "Error Message": CrawlQueue.error_message,
    }
    query = _apply_sorting(
        query,
        query_args.sort_by,
        query_args.sort_asc,
        sort_map,
        CrawlQueue.id,
    )

    total = query.count()
    offset = (query_args.page - 1) * query_args.page_size
    items_list = [format_crawl_queue_item(q) for q in query.offset(offset).limit(query_args.page_size).all()]

    return {
        "items": items_list,
        "total": total,
        "page": query_args.page,
        "page_size": query_args.page_size,
        "total_pages": (total + query_args.page_size - 1) // query_args.page_size if total > 0 else 1,
    }


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
    job = db.query(Job).filter(Job.id == query_args.job_id).first()
    if not job or job.user_id != query_args.user_id:
        raise ValueError("無權限存取此任務。")

    if query_args.group_by == "source":
        return _get_internal_errors_grouped_by_source(db, query_args)

    query = db.query(CrawlQueue).filter(
        CrawlQueue.job_id == query_args.job_id,
        CrawlQueue.status.in_(["failed", "warning"]),
    )
    query = apply_internal_result_filters(query, query_args.status_filter)
    return _get_internal_errors_no_grouping(query, query_args)
