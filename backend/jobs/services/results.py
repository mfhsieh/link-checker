# pylint: disable=too-many-lines
"""
任務結果與統計查詢邏輯。
"""

import json
import logging
from collections import defaultdict
from collections.abc import Iterable, Iterator

from sqlalchemy import String, asc, case, cast, desc
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


def _group_by_target(links: Iterable[ExternalLink]) -> list[dict[str, object]]:
    """
    依外部目標連結去重聚合。

    Args:
        links (Iterable[ExternalLink]): 欲聚合的外連記錄迭代器。

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

    return [{**v, "source_urls": sorted(list(v["source_urls"]))[:10]} for v in agg.values()]


def _group_by_domain(links: Iterable[ExternalLink]) -> list[dict[str, object]]:
    """
    依外部目標網域聚合，產出網域分佈統計報表。

    Args:
        links (Iterable[ExternalLink]): 欲聚合的外連記錄迭代器。

    Returns:
        list[dict[str, object]]: 聚合後的結果列表。
    """
    agg: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "domain": "",
            "occurrence_count": 0,
            "unique_urls": set(),
            "source_urls": set(),
        }
    )
    for lnk in links:
        dom = get_domain(lnk.target_url) or "unknown"
        d = agg[dom]
        d["domain"] = dom
        d["occurrence_count"] += 1
        d["unique_urls"].add(lnk.target_url)
        d["source_urls"].add(lnk.source_url)

    result = []
    for v in agg.values():
        result.append({
            "domain": v["domain"],
            "occurrence_count": v["occurrence_count"],
            "unique_urls_count": len(v["unique_urls"]),
            "unique_urls": sorted(list(v["unique_urls"])[:10]),
            "source_urls": sorted(list(v["source_urls"])[:10]),
        })
    # 依出現次數降冪排序
    result.sort(key=lambda x: x["occurrence_count"], reverse=True)
    return result


def _group_by_source(links: Iterable[ExternalLink]) -> list[dict[str, object]]:
    """
    依自家網頁(Source URL)聚合，產出修補視角報表。

    Args:
        links (Iterable[ExternalLink]): 欲聚合的外連記錄迭代器。

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
        if len(d["targets"]) < 10:
            d["targets"].append({
                "url": lnk.target_url,
                "status": status_str,
                "is_secure": lnk.is_secure,
                "error_message": lnk.error_message,
            })

    return [{**v} for v in agg.values()]


def get_job_results(  # pylint: disable=too-many-locals, too-many-branches, too-many-statements
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

    def apply_py_filter_sort(items_list: list[dict[str, object]]) -> list[dict[str, object]]:
        """
        在記憶體中套用前端指定的欄位過濾與排序邏輯。

        Args:
            items_list (list[dict[str, object]]): 尚未過濾與排序的項目清單。

        Returns:
            list[dict[str, object]]: 過濾與排序後的項目清單。
        """
        if query_args.col_filters:
            try:
                filters = json.loads(query_args.col_filters)
                filtered = []
                for item in items_list:
                    match = True
                    for k, v in filters.items():
                        if not v:
                            continue
                        v_str = str(v).lower()
                        val = item.get(k)
                        if k == "is_secure":
                            val_str = "✓" if val else "✗"
                        else:
                            val_str = str(val).lower() if val is not None else ""
                        if v_str not in val_str:
                            match = False
                            break
                    if match:
                        filtered.append(item)
                items_list = filtered
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass

        if query_args.sort_by:
            sort_k = query_args.sort_by
            rev = not query_args.sort_asc

            def sort_key(x: dict[str, object]) -> object:
                """
                產生排序用的鍵值。

                Args:
                    x (dict[str, object]): 單筆項目。

                Returns:
                    object: 用於排序的比較鍵值。
                """
                val = x.get(sort_k)
                if val is None:
                    return ""
                if isinstance(val, (int, float, bool)):
                    return val
                return str(val).lower()

            try:
                items_list.sort(key=sort_key, reverse=rev)
            except TypeError:
                pass
        return items_list

    if query_args.group_by == "target":
        links = query.order_by(ExternalLink.created_at).yield_per(2000)
        items_list = _group_by_target(links)
        items_list = apply_py_filter_sort(items_list)
    elif query_args.group_by == "source":
        links = query.order_by(ExternalLink.created_at).yield_per(2000)
        items_list = _group_by_source(links)
        items_list = apply_py_filter_sort(items_list)
    elif query_args.group_by == "domain":
        links = query.order_by(ExternalLink.created_at).yield_per(2000)
        items_list = _group_by_domain(links)
        items_list = apply_py_filter_sort(items_list)
    else:
        if query_args.col_filters:
            try:
                filters = json.loads(query_args.col_filters)
                for k, v in filters.items():
                    if not v:
                        continue
                    v_str = str(v).lower()
                    if k == "target_url":
                        query = query.filter(ExternalLink.target_url.ilike(f"%{v_str}%"))
                    elif k == "source_url":
                        query = query.filter(ExternalLink.source_url.ilike(f"%{v_str}%"))
                    elif k == "ip_address":
                        query = query.filter(ExternalLink.ip_address.ilike(f"%{v_str}%"))
                    elif k == "is_secure":
                        is_sec = v_str in ("true", "1", "yes", "✓", "v", "t")
                        query = query.filter(ExternalLink.is_secure.is_(is_sec))
                    elif k == "http_status_code":
                        query = query.filter(cast(ExternalLink.http_status_code, String).ilike(f"%{v_str}%"))
                    elif k == "error_message":
                        query = query.filter(ExternalLink.error_message.ilike(f"%{v_str}%"))
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass

        if query_args.sort_by:
            col = None
            if query_args.sort_by == "target_url":
                col = ExternalLink.target_url
            elif query_args.sort_by == "source_url":
                col = ExternalLink.source_url
            elif query_args.sort_by == "ip_address":
                col = ExternalLink.ip_address
            elif query_args.sort_by == "is_secure":
                col = ExternalLink.is_secure
            elif query_args.sort_by == "http_status_code":
                col = ExternalLink.http_status_code
            elif query_args.sort_by == "error_message":
                col = ExternalLink.error_message
            if col is not None:
                order_func = asc if query_args.sort_asc else desc
                query = query.order_by(order_func(col))
        else:
            query = query.order_by(ExternalLink.created_at)

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


def _get_grouped_results_summary(query: Query, group_by: str) -> dict[str, int]:  # pylint: disable=too-many-locals, too-many-branches
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
    set_not_found = set()
    set_server_error = set()
    set_connection_error = set()
    set_other_error = set()
    set_blocked = set()
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
        c = lnk.http_status_code
        is_blocked = c in (401, 403, 405, 406, 429)
        is_insecure = not lnk.is_secure
        is_healthy = bool(lnk.ip_address) and c is not None and c < 400

        is_not_found = c in (404, 410)
        is_server_error = c is not None and 500 <= c < 600
        is_connection_error = c is None and bool(lnk.ip_address)
        is_other_error = c is not None and ((c >= 400 and c < 500 and not is_blocked and not is_not_found) or c >= 600)  # pylint: disable=chained-comparison

        if is_dns_failed:
            set_dns_failed.add(key)
        if is_not_found:
            set_not_found.add(key)
        if is_server_error:
            set_server_error.add(key)
        if is_connection_error:
            set_connection_error.add(key)
        if is_other_error:
            set_other_error.add(key)
        if is_blocked:
            set_blocked.add(key)
        if is_insecure:
            set_insecure.add(key)
        if is_healthy:
            set_healthy.add(key)

    return {
        "total_external": len(set_all),
        "dns_failed": len(set_dns_failed),
        "not_found": len(set_not_found),
        "server_error": len(set_server_error),
        "connection_error": len(set_connection_error),
        "other_error": len(set_other_error),
        "blocked": len(set_blocked),
        "insecure": len(set_insecure),
        "healthy_count": len(set_healthy),
    }


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

        healthy_count = (
            total_external - dns_failed - not_found - server_error - connection_error - other_error - blocked
        )

    else:
        query = db.query(ExternalLink).filter(ExternalLink.job_id == job_id)
        query = apply_job_result_filters(query, exclude=exclude)
        stats_dict = _get_grouped_results_summary(query, group_by)
        total_external = stats_dict["total_external"]
        dns_failed = stats_dict["dns_failed"]
        not_found = stats_dict["not_found"]
        server_error = stats_dict["server_error"]
        connection_error = stats_dict["connection_error"]
        other_error = stats_dict["other_error"]
        blocked = stats_dict["blocked"]
        insecure = stats_dict["insecure"]
        healthy_count = stats_dict["healthy_count"]

    return {
        "job_id": job_id,
        "total_crawled_pages": total_queue,
        "total_external_links": total_external,
        "healthy_count": healthy_count,
        "dns_failed_count": dns_failed,
        "not_found_count": not_found,
        "server_error_count": server_error,
        "connection_error_count": connection_error,
        "other_error_count": other_error,
        "blocked_count": blocked,
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
        diff_lists["ip_changed"].append({
            "target_url": url,
            "old_ip": item_a["ip"],
            "new_ip": item_b["ip"],
            "sources": sorted(list(item_b["sources"])[:10]),
        })
    if item_a["is_secure"] and not item_b["is_secure"]:
        diff_lists["security_downgraded"].append({"target_url": url, "sources": sorted(list(item_b["sources"])[:10])})

    a_bad = _is_bad_link(item_a)
    b_bad = _is_bad_link(item_b)

    if not a_bad and b_bad:
        diff_lists["degraded"].append({
            "target_url": url,
            "old_status": item_a["status_code"],
            "old_error": item_a["error"],
            "new_status": item_b["status_code"],
            "new_error": item_b["error"],
            "sources": sorted(list(item_b["sources"])[:10]),
        })
    elif a_bad and not b_bad:
        diff_lists["recovered"].append({
            "target_url": url,
            "old_status": item_a["status_code"],
            "old_error": item_a["error"],
            "new_status": item_b["status_code"],
            "new_error": item_b["error"],
            "sources": sorted(list(item_b["sources"])[:10]),
        })


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
        result.append({
            "domain": v["domain"],
            "occurrence_count": v["occurrence_count"],
            "unique_urls_count": len(v["unique_urls"]),
            "unique_urls": sorted(list(v["unique_urls"])),
            "source_urls": sorted(list(v["source_urls"])),
        })
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
        d["targets"].append({
            "url": lnk.target_url,
            "status": status_str,
            "is_secure": lnk.is_secure,
            "error_message": lnk.error_message,
        })
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
    job_id: str,
    user_id: str,
    status_filter: str | None = None,
    group_by: str = "none",
) -> Iterator[dict[str, object]]:
    """
    查詢任務的內部失效紀錄，並以 yield 串流回傳。

    Args:
        db (DBSession): Crawler DB Session。
        job_id (str): 任務 ID。
        user_id (str): 請求查詢的使用者 ID。
        status_filter (str | None): 狀態篩選。
        group_by (str): 聚合方式。

    Yields:
        dict[str, object]: 單筆內部失敗結果字典。

    Raises:
        ValueError: 找不到任務或無權限存取時拋出。
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job or job.user_id != user_id:
        raise ValueError("無權限存取此任務。")

    query = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.status.in_(["failed", "warning"]))
    query = apply_internal_result_filters(query, status_filter)

    if group_by == "source":
        # 呼叫既有的分頁查詢函數，但直接索取所有匹配結果並利用它實作的聚合演算法
        results = get_internal_errors(
            db, job_id, user_id, status_filter, group_by, page=1, page_size=9999999, truncate_lists=False
        )
        yield from results["items"]  # type: ignore
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


# pylint: disable=too-many-locals
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
                        & (
                            (CrawlQueue.error_message.ilike("%timeout%"))
                            | (CrawlQueue.error_message.ilike("%timed out%"))
                        ),
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

    set_all = set()
    set_not_found = set()
    set_server_error = set()
    set_access_denied = set()
    set_timeout = set()
    set_connection_error = set()
    set_other_error = set()
    set_warning = set()

    query = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.status.in_(["failed", "warning"]))
    for q in query.yield_per(2000):
        key = q.source_url or "" if group_by == "source" else q.id
        set_all.add(key)

        c = q.status_code
        msg = str(q.error_message or "").lower()

        if q.status == "warning":
            set_warning.add(key)
        elif c in (404, 410):
            set_not_found.add(key)
        elif c is not None and 500 <= c < 600:
            set_server_error.add(key)
        elif c in (401, 403):
            set_access_denied.add(key)
        elif c is None and ("timeout" in msg or "timed out" in msg):
            set_timeout.add(key)
        elif c is None and not ("timeout" in msg or "timed out" in msg):
            set_connection_error.add(key)
        else:
            set_other_error.add(key)

    return {
        "total": len(set_all),
        "server_error": len(set_server_error),
        "connection_error": len(set_connection_error),
        "timeout": len(set_timeout),
        "not_found": len(set_not_found),
        "other_error": len(set_other_error),
        "warning": len(set_warning),
        "access_denied": len(set_access_denied),
    }


# pylint: disable=too-many-arguments, too-many-locals, too-many-branches, too-many-statements
def get_internal_errors(
    db: DBSession,
    job_id: str,
    user_id: str,
    status_filter: str | None = None,
    group_by: str = "none",
    page: int = 1,
    page_size: int = 50,
    truncate_lists: bool = True,
    sort_by: str | None = None,
    sort_asc: bool = True,
    col_filters: str | None = None,
) -> dict[str, object]:
    """
    取得任務內部網頁爬取失敗的紀錄列表。

    Args:
        db (DBSession): Crawler DB Session。
        job_id (str): 任務 ID。
        user_id (str): 請求查詢的使用者 ID。
        status_filter (str | None): 狀態篩選。
        group_by (str): 聚合方式。
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

    query = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.status.in_(["failed", "warning"]))
    query = apply_internal_result_filters(query, status_filter)

    def apply_py_filter_sort(items_list: list[dict[str, object]]) -> list[dict[str, object]]:
        """
        在記憶體中套用前端指定的欄位過濾與排序邏輯。

        Args:
            items_list (list[dict[str, object]]): 尚未過濾與排序的項目清單。

        Returns:
            list[dict[str, object]]: 過濾與排序後的項目清單。
        """
        if col_filters:
            try:
                filters = json.loads(col_filters)
                filtered = []
                for item in items_list:
                    match = True
                    for k, v in filters.items():
                        if not v:
                            continue
                        v_str = str(v).lower()
                        val = item.get(k)
                        val_str = str(val).lower() if val is not None else ""
                        if v_str not in val_str:
                            match = False
                            break
                    if match:
                        filtered.append(item)
                items_list = filtered
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
        if sort_by:
            rev = not sort_asc

            def sort_key(x: dict[str, object]) -> object:
                """
                產生排序用的鍵值。

                Args:
                    x (dict[str, object]): 單筆項目。

                Returns:
                    object: 用於排序的比較鍵值。
                """
                val = x.get(sort_by)
                if val is None:
                    return ""
                if isinstance(val, (int, float, bool)):
                    return val
                return str(val).lower()

            try:
                items_list.sort(key=sort_key, reverse=rev)
            except TypeError:
                pass
        return items_list

    if group_by == "source":
        links = query.order_by(CrawlQueue.id).yield_per(2000)
        agg: dict[str, dict[str, object]] = defaultdict(
            lambda: {"source_url": "", "occurrence_count": 0, "targets": []}
        )
        for q in links:
            s_url = q.source_url or ""
            d = agg[s_url]
            d["source_url"] = s_url
            d["occurrence_count"] += 1
            if not truncate_lists or len(d["targets"]) < 10:
                d["targets"].append({
                    "url": q.url,
                    "status": str(q.status_code) if q.status_code is not None else "Error",
                    "error_message": q.error_message,
                })

        items_list = list(agg.values())
        if not sort_by:
            items_list.sort(key=lambda x: x["occurrence_count"], reverse=True)

        items_list = apply_py_filter_sort(items_list)

        total = len(items_list)
        offset = (page - 1) * page_size
        items = items_list[offset : offset + page_size]
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    if col_filters:
        try:
            filters = json.loads(col_filters)
            for k, v in filters.items():
                if not v:
                    continue
                v_str = str(v).lower()
                if k == "URL":
                    query = query.filter(CrawlQueue.url.ilike(f"%{v_str}%"))
                elif k == "Source URL":
                    query = query.filter(CrawlQueue.source_url.ilike(f"%{v_str}%"))
                elif k == "HTTP Status Code":
                    query = query.filter(cast(CrawlQueue.status_code, String).ilike(f"%{v_str}%"))
                elif k == "Error Message":
                    query = query.filter(CrawlQueue.error_message.ilike(f"%{v_str}%"))
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass

    if sort_by:
        col = None
        if sort_by == "URL":
            col = CrawlQueue.url
        elif sort_by == "Source URL":
            col = CrawlQueue.source_url
        elif sort_by == "HTTP Status Code":
            col = CrawlQueue.status_code
        elif sort_by == "Error Message":
            col = CrawlQueue.error_message
        if col is not None:
            order_func = asc if sort_asc else desc
            query = query.order_by(order_func(col))
    else:
        query = query.order_by(CrawlQueue.id)

    total = query.count()
    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()

    items_list = [format_crawl_queue_item(q) for q in items]

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return {
        "items": items_list,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
