"""
任務結果與統計查詢邏輯。
"""

import logging
from collections import defaultdict
from collections.abc import Iterator

from sqlalchemy import case
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.sql.functions import count
from sqlalchemy.sql.functions import sum as sql_sum

from backend.jobs.schemas import JobResultQuery
from crawler.exporter import format_crawl_queue_item
from crawler.models import CrawlQueue, ExternalLink, Job, apply_job_result_filters
from crawler.utils import (
    get_domain,
)

logger: logging.Logger = logging.getLogger(__name__)


def _group_by_target(links: list[ExternalLink]) -> list[dict[str, object]]:
    """
    依外部目標連結去重聚合。

    Args:
        links (list[ExternalLink]): 欲聚合的外連記錄列表。

    Returns:
        list[dict[str, object]]: 聚合後的結果列表。
    """
    agg: dict[str, dict[str, object]] = defaultdict(
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
    for lnk in links:
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

    return [{**v, "source_urls": sorted(list(v["source_urls"]))} for v in agg.values()]


def _group_by_domain(links: list[ExternalLink]) -> list[dict[str, object]]:
    """
    依外部目標網域聚合，產出網域分佈統計報表。

    Args:
        links (list[ExternalLink]): 欲聚合的外連記錄列表。

    Returns:
        list[dict[str, object]]: 聚合後的結果列表。
    """
    agg: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "domain": "",
            "occurrence_count": 0,
            "unique_urls": set(),
        }
    )
    for lnk in links:
        dom = get_domain(lnk.target_url) or "unknown"
        d = agg[dom]
        d["domain"] = dom
        d["occurrence_count"] += 1
        d["unique_urls"].add(lnk.target_url)

    result = []
    for v in agg.values():
        result.append(
            {
                "domain": v["domain"],
                "occurrence_count": v["occurrence_count"],
                "unique_urls_count": len(v["unique_urls"]),
                "unique_urls": sorted(list(v["unique_urls"])),
            }
        )
    # 依出現次數降冪排序
    result.sort(key=lambda x: x["occurrence_count"], reverse=True)
    return result


def _group_by_source(links: list[ExternalLink]) -> list[dict[str, object]]:
    """
    依自家網頁(Source URL)聚合，產出修補視角報表。

    Args:
        links (list[ExternalLink]): 欲聚合的外連記錄列表。

    Returns:
        list[dict[str, object]]: 聚合後的結果列表。
    """
    agg: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "source_url": "",
            "occurrence_count": 0,
            "targets": [],
        }
    )
    for lnk in links:
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

    return [{**v} for v in agg.values()]


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

    query = db.query(ExternalLink).filter(ExternalLink.job_id == query_args.job_id)
    query = apply_job_result_filters(
        query, search=query_args.search, exclude=query_args.exclude, status_filter=query_args.status_filter
    )

    if query_args.group_by == "target":
        links = query.order_by(ExternalLink.created_at).all()
        items_list = _group_by_target(links)
    elif query_args.group_by == "source":
        links = query.order_by(ExternalLink.created_at).all()
        items_list = _group_by_source(links)
    elif query_args.group_by == "domain":
        links = query.order_by(ExternalLink.created_at).all()
        items_list = _group_by_domain(links)
    else:
        total = query.count()
        offset = (query_args.page - 1) * query_args.page_size
        links = query.order_by(ExternalLink.created_at).offset(offset).limit(query_args.page_size).all()
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

    total = len(items_list)
    offset = (query_args.page - 1) * query_args.page_size
    items = items_list[offset : offset + query_args.page_size]

    total_pages = (total + query_args.page_size - 1) // query_args.page_size if total > 0 else 1

    return {
        "items": items,
        "total": total,
        "page": query_args.page,
        "page_size": query_args.page_size,
        "total_pages": total_pages,
    }


def _get_grouped_results_summary(query: Query, group_by: str) -> dict[str, int]:
    """
    計算分組後的聚合統計結果。

    Args:
        query (Query): SQLAlchemy 查詢物件。
        group_by (str): 分組依據。

    Returns:
        dict[str, int]: 包含 total, healthy_count, dns_failed_count, http_error_count, insecure_count 的統計結果。
    """
    set_all = set()
    set_dns_failed = set()
    set_http_errors = set()
    set_insecure = set()
    set_healthy = set()

    for lnk in query.yield_per(2000):
        if group_by == "target":
            key = lnk.target_url
        elif group_by == "source":
            key = lnk.source_url
        elif group_by == "domain":
            key = get_domain(lnk.target_url) or "unknown"
        else:
            key = lnk.id

        set_all.add(key)

        is_dns_failed = not lnk.ip_address
        is_http_error = (lnk.http_status_code is not None and lnk.http_status_code >= 400) or (
            lnk.http_status_code is None and bool(lnk.ip_address)
        )
        is_insecure = not lnk.is_secure
        is_healthy = bool(lnk.ip_address) and lnk.http_status_code is not None and lnk.http_status_code < 400

        if is_dns_failed:
            set_dns_failed.add(key)
        if is_http_error:
            set_http_errors.add(key)
        if is_insecure:
            set_insecure.add(key)
        if is_healthy:
            set_healthy.add(key)

    return {
        "total_external": len(set_all),
        "dns_failed": len(set_dns_failed),
        "http_errors": len(set_http_errors),
        "insecure": len(set_insecure),
        "healthy_count": len(set_healthy),
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
            sql_sum(
                case(
                    (
                        (ExternalLink.http_status_code >= 400)
                        | (
                            (ExternalLink.http_status_code.is_(None))
                            & (ExternalLink.ip_address.isnot(None))
                            & (ExternalLink.ip_address != "")
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("http_errors"),
            sql_sum(case((ExternalLink.is_secure.is_(False), 1), else_=0)).label("insecure"),
        ).filter(ExternalLink.job_id == job_id)

        query = apply_job_result_filters(query, exclude=exclude)

        stats = query.first()

        total_external = int(stats.total) if stats and stats.total else 0
        dns_failed = int(stats.dns_failed) if stats and stats.dns_failed else 0
        http_errors = int(stats.http_errors) if stats and stats.http_errors else 0
        insecure = int(stats.insecure) if stats and stats.insecure else 0

        healthy_count = total_external - dns_failed - http_errors

    else:
        query = db.query(ExternalLink).filter(ExternalLink.job_id == job_id)
        query = apply_job_result_filters(query, exclude=exclude)
        stats_dict = _get_grouped_results_summary(query, group_by)
        total_external = stats_dict["total_external"]
        dns_failed = stats_dict["dns_failed"]
        http_errors = stats_dict["http_errors"]
        insecure = stats_dict["insecure"]
        healthy_count = stats_dict["healthy_count"]

    return {
        "job_id": job_id,
        "total_crawled_pages": total_queue,
        "total_external_links": total_external,
        "healthy_count": healthy_count,
        "dns_failed_count": dns_failed,
        "http_error_count": http_errors,
        "insecure_count": insecure,
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
    """
    if item_a["ip"] and item_b["ip"] and item_a["ip"] != item_b["ip"]:
        diff_lists["ip_changed"].append(
            {
                "target_url": url,
                "old_ip": item_a["ip"],
                "new_ip": item_b["ip"],
                "sources": sorted(list(item_b["sources"])),
            }
        )
    if item_a["is_secure"] and not item_b["is_secure"]:
        diff_lists["security_downgraded"].append({"target_url": url, "sources": sorted(list(item_b["sources"]))})

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
                "sources": sorted(list(item_b["sources"])),
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
                "sources": sorted(list(item_b["sources"])),
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
            "sources": sorted(list(dict_b[url]["sources"])),
        }
        for url in (set_b - set_a)
    ]

    removed_links = [
        {
            "target_url": url,
            "old_ip": dict_a[url]["ip"],
            "old_status_code": dict_a[url]["status_code"],
            "old_error": dict_a[url]["error"],
            "sources": sorted(list(dict_a[url]["sources"])),
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
    agg = defaultdict(lambda: {"domain": "", "occurrence_count": 0, "unique_urls": set()})
    for lnk in cursor:
        dom = get_domain(lnk.target_url) or "unknown"
        d = agg[dom]
        d["domain"] = dom
        d["occurrence_count"] += 1
        d["unique_urls"].add(lnk.target_url)

    result = []
    for v in agg.values():
        result.append(
            {
                "domain": v["domain"],
                "occurrence_count": v["occurrence_count"],
                "unique_urls_count": len(v["unique_urls"]),
                "unique_urls": sorted(list(v["unique_urls"])),
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


def get_internal_errors(
    db: DBSession, job_id: str, user_id: str, page: int = 1, page_size: int = 50
) -> dict[str, object]:
    """
    取得任務內部網頁爬取失敗的紀錄列表。

    Args:
        db (DBSession): Crawler DB Session。
        job_id (str): 任務 ID。
        user_id (str): 請求查詢的使用者 ID。
        page (int): 頁碼。
        page_size (int): 每頁筆數。

    Returns:
        dict[str, object]: 查詢結果的字典。

    Raises:
        ValueError: 找不到任務或無權限存取時拋出。
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job or job.user_id != user_id:
        raise ValueError("無權限存取此任務。")

    query = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.status == "failed")

    total = query.count()
    offset = (page - 1) * page_size
    items = query.order_by(CrawlQueue.id).offset(offset).limit(page_size).all()

    items_list = [format_crawl_queue_item(q) for q in items]

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return {
        "items": items_list,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
