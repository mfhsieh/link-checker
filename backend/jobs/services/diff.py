"""
diff.py — 任務歷史差異比對服務模組

專責處理兩次爬蟲任務之間（基準任務 Job A vs 對照任務 Job B）的外部連結與內部連結差異比對。
支援持續失效 (Persistently Failed) 診斷、狀態變遷追蹤與範疇篩選。
"""

from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session as DBSession

from crawler.models import CrawlQueue, ExternalLink, Job


def _build_external_dict_for_diff(db: DBSession, job_id: str, exclude: str | None = None) -> dict[str, dict[str, Any]]:
    """
    為指定任務建立外部目標網址的聚合字典，供 Diff 比對使用。

    針對指定任務 ID 的外部連結紀錄進行聚合，整理出目標網址的 IP、資安狀態、HTTP 狀態碼、
    錯誤訊息與來源頁面集合。

    Args:
        db (DBSession): Crawler DB Session。
        job_id (str): 任務 ID。
        exclude (str | None): 要排除的目標網域，以點號或名稱模糊比對。

    Returns:
        dict[str, dict[str, Any]]: 聚合後的外連字典，Key 為目標 URL。
    """
    agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "ip": None,
            "is_secure": True,
            "status_code": None,
            "status_category": None,
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
        sources = d["sources"]
        if isinstance(sources, set):
            sources.add(lnk.source_url)
        d["is_secure"] = d["is_secure"] and lnk.is_secure
        if not d["ip"] and lnk.ip_address:
            d["ip"] = lnk.ip_address
        if d["status_code"] is None and lnk.http_status_code is not None:
            d["status_code"] = lnk.http_status_code
        if d["status_category"] is None and lnk.status_category:
            d["status_category"] = lnk.status_category
        if not d["error"] and lnk.error_message:
            d["error"] = lnk.error_message
    return {k: dict(v) for k, v in agg.items()}


def _is_bad_external_link(item: dict[str, Any]) -> bool:
    """
    判斷給定的外連項目是否處於異常/失敗狀態。

    若缺少 IP 位址、HTTP 狀態碼大於等於 400 或帶有錯誤訊息，即判定為異常連結。

    Args:
        item (dict[str, Any]): 外連項目的字典資料。

    Returns:
        bool: 若為異常/失效連結則回傳 True，否則回傳 False。
    """
    if not item.get("ip"):
        return True
    status_code = item.get("status_code")
    if status_code is not None and int(str(status_code)) >= 400:
        return True
        
    cat = item.get("status_category")
    if cat in ["failed", "error", "timeout", "blocked", "connection_error", "dns_failed", "not_found", "server_error", "other_error"]:
        return True
        
    # 正常、略過或完成的連結，即使 error 中有提示訊息，也不視為異常死鏈
    if cat in ["healthy", "skip", "completed", "warning"]:
        return False
        
    if item.get("error"):
        return True
    return False


def _get_sorted_sources(item: dict[str, Any]) -> list[str]:
    """
    取得外連項目中排序後的來源網址。

    Args:
        item (dict[str, Any]): 外連項目的字典資料。

    Returns:
        list[str]: 來源網址組成的清單。
    """
    sources = item.get("sources", set())
    if isinstance(sources, (set, list)):
        return sorted([str(s) for s in sources])
    return []


def _extract_domain(url: str) -> str:
    """
    從 URL 提取網域 (Hostname)。

    Args:
        url (str): 網址。

    Returns:
        str: 網域或原始字串。
    """
    try:
        parsed = urlparse(url)
        return parsed.hostname or url
    except (ValueError, AttributeError):
        return url


def _compare_external_links(  # pylint: disable=too-many-locals
    dict_a: dict[str, dict[str, Any]],
    dict_b: dict[str, dict[str, Any]],
) -> tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
    """
    比對兩次任務的外部連結差異。

    計算 IP 異動（以網域 IP 集合無交集變更為準，消除 CDN 誤報）、資安降級 (HTTPS 轉 HTTP)、
    品質劣化、品質復原、持續失敗、新增外連與消失外連。

    Args:
        dict_a (dict[str, dict[str, Any]]): 基準任務 (Job A) 的外連字典。
        dict_b (dict[str, dict[str, Any]]): 對照任務 (Job B) 的外連字典。

    Returns:
        tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
            二元組，包含 (統計數量摘要字典, 詳細變遷紀錄列表字典)。
    """
    set_a = set(dict_a.keys())
    set_b = set(dict_b.keys())

    diff_lists: dict[str, list[dict[str, Any]]] = {
        "ip_changed": [],
        "degraded": [],
        "recovered": [],
    }

    # 1. 網域層級 IP 集合與 URL 統計 (用於精確判定 IP 異動與消除 CDN/多 IP 輪詢誤報)
    domain_data_a: dict[str, dict[str, Any]] = defaultdict(lambda: {"ips": set(), "urls": set(), "sources": set()})
    domain_data_b: dict[str, dict[str, Any]] = defaultdict(lambda: {"ips": set(), "urls": set(), "sources": set()})

    for url, item in dict_a.items():
        dom = _extract_domain(url)
        if item.get("ip"):
            domain_data_a[dom]["ips"].add(item["ip"])
        domain_data_a[dom]["urls"].add(url)
        domain_data_a[dom]["sources"].update(item.get("sources", set()))

    for url, item in dict_b.items():
        dom = _extract_domain(url)
        if item.get("ip"):
            domain_data_b[dom]["ips"].add(item["ip"])
        domain_data_b[dom]["urls"].add(url)
        domain_data_b[dom]["sources"].update(item.get("sources", set()))

    common_domains = set(domain_data_a.keys()) & set(domain_data_b.keys())
    for dom in sorted(common_domains):
        ips_a = domain_data_a[dom]["ips"]
        ips_b = domain_data_b[dom]["ips"]
        if ips_a and ips_b and not ips_a.intersection(ips_b):
            diff_lists["ip_changed"].append(
                {
                    "domain": dom,
                    "target_url": sorted(list(domain_data_b[dom]["urls"]))[0],
                    "old_ip": ", ".join(sorted(ips_a)),
                    "new_ip": ", ".join(sorted(ips_b)),
                    "url_count": len(domain_data_b[dom]["urls"]),
                    "target_urls": sorted(list(domain_data_b[dom]["urls"]))[:10],
                    "sources": sorted([str(s) for s in domain_data_b[dom]["sources"]])[:10],
                }
            )

    for url in set_a & set_b:
        item_a = dict_a[url]
        item_b = dict_b[url]

        a_bad = _is_bad_external_link(item_a)
        b_bad = _is_bad_external_link(item_b)

        sec_downgraded = item_a["is_secure"] and not item_b["is_secure"]
        sec_upgraded = not item_a["is_secure"] and item_b["is_secure"]

        # 2. 狀態品質與安全協定變遷 (Degraded)
        if (not a_bad and b_bad) or (not a_bad and not b_bad and sec_downgraded):
            old_err = item_a["error"]
            new_err = item_b["error"]

            if not a_bad and b_bad:
                old_st = str(item_a["status_code"]) if item_a.get("status_code") is not None else "200"
                new_st = str(item_b["status_code"]) if item_b.get("status_code") is not None else "連線失敗"
                if sec_downgraded:
                    new_err = "安全降級 (HTTPS ➔ HTTP)" + (f" ({new_err})" if new_err else "")
            else:
                st_a = f" ({item_a['status_code']})" if item_a.get("status_code") else ""
                st_b = f" ({item_b['status_code']})" if item_b.get("status_code") else ""
                old_st = f"HTTPS{st_a}"
                new_st = f"HTTP{st_b}"
                new_err = "安全降級 (HTTPS ➔ HTTP)"

            diff_lists["degraded"].append(
                {
                    "target_url": url,
                    "old_status": old_st,
                    "old_error": old_err,
                    "new_status": new_st,
                    "new_error": new_err,
                    "sources": _get_sorted_sources(item_b),
                }
            )
        # 3. 狀態品質與安全協定變遷 (Recovered)
        elif (a_bad and not b_bad) or (not a_bad and not b_bad and sec_upgraded):
            old_err = item_a["error"]
            new_err = item_b["error"]

            if a_bad and not b_bad:
                old_st = str(item_a["status_code"]) if item_a.get("status_code") is not None else "連線失敗"
                new_st = str(item_b["status_code"]) if item_b.get("status_code") is not None else "200"
                if sec_upgraded:
                    new_err = "安全升級 (HTTP ➔ HTTPS)"
            else:
                st_a = f" ({item_a['status_code']})" if item_a.get("status_code") else ""
                st_b = f" ({item_b['status_code']})" if item_b.get("status_code") else ""
                old_st = f"HTTP{st_a}"
                new_st = f"HTTPS{st_b}"
                new_err = "安全升級 (HTTP ➔ HTTPS)"

            diff_lists["recovered"].append(
                {
                    "target_url": url,
                    "old_status": old_st,
                    "old_error": old_err,
                    "new_status": new_st,
                    "new_error": new_err,
                    "sources": _get_sorted_sources(item_b),
                }
            )

    new_links = [
        {
            "target_url": url,
            "ip": dict_b[url]["ip"],
            "is_secure": dict_b[url]["is_secure"],
            "status_code": dict_b[url]["status_code"],
            "error": dict_b[url]["error"],
            "sources_count": len(dict_b[url]["sources"]),
            "sources": _get_sorted_sources(dict_b[url]),
        }
        for url in (set_b - set_a)
    ]

    removed_links = [
        {
            "target_url": url,
            "old_ip": dict_a[url]["ip"],
            "old_is_secure": dict_a[url]["is_secure"],
            "old_status_code": dict_a[url]["status_code"],
            "old_error": dict_a[url]["error"],
            "sources_count": len(dict_a[url]["sources"]),
            "sources": _get_sorted_sources(dict_a[url]),
        }
        for url in (set_a - set_b)
    ]

    summary = {
        "ip_changed": len(diff_lists["ip_changed"]),
        "degraded": len(diff_lists["degraded"]),
        "recovered": len(diff_lists["recovered"]),
        "new_links": len(new_links),
        "removed_links": len(removed_links),
    }

    details = {
        "ip_changed": diff_lists["ip_changed"],
        "degraded": diff_lists["degraded"],
        "recovered": diff_lists["recovered"],
        "new_links": new_links,
        "removed_links": removed_links,
    }

    return summary, details


def _build_internal_dict_for_diff(db: DBSession, job_id: str) -> dict[str, dict[str, Any]]:
    query = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id)
    records: dict[str, dict[str, Any]] = {}
    cursor = query.yield_per(2000)
    for rec in cursor:
        url_str = rec.url or ""
        records[url_str] = {
            "url": url_str,
            "status_code": rec.status_code,
            "status_category": rec.status_category,
            "error": rec.error_message,
            "depth": rec.depth,
            "is_secure": url_str.startswith("https://"),
        }
    return records


def _is_bad_internal_record(item: dict[str, Any]) -> bool:
    status_code = item.get("status_code")
    if status_code is not None and int(str(status_code)) >= 400:
        return True
        
    cat = item.get("status_category")
    if cat in ["failed", "error", "timeout", "blocked", "connection_error", "not_found", "server_error"]:
        return True
        
    # 正常略過 (skip) 或 成功完成 (completed) 的網頁，
    # 即使 error_message 中有附加資訊 (例如: "略過非目標 MIME 類型", "重導向至外部網域")，
    # 也絕不應視為異常死鏈
    if cat in ["skip", "completed", "healthy"]:
        return False
        
    if item.get("error"):
        return True
    return False


def _compare_internal_links(
    dict_a: dict[str, dict[str, Any]],
    dict_b: dict[str, dict[str, Any]],
) -> tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
    set_a = set(dict_a.keys())
    set_b = set(dict_b.keys())

    diff_lists: dict[str, list[dict[str, Any]]] = {
        "degraded": [],
        "recovered": [],
    }

    for url in set_a & set_b:
        item_a = dict_a[url]
        item_b = dict_b[url]

        a_bad = _is_bad_internal_record(item_a)
        b_bad = _is_bad_internal_record(item_b)

        sec_downgraded = item_a["is_secure"] and not item_b["is_secure"]
        sec_upgraded = not item_a["is_secure"] and item_b["is_secure"]

        # 1. 內部頁面劣化 (Degraded)
        if (not a_bad and b_bad) or (not a_bad and not b_bad and sec_downgraded):
            old_err = item_a["error"]
            new_err = item_b["error"]

            if not a_bad and b_bad:
                old_st = str(item_a["status_code"]) if item_a.get("status_code") is not None else "200"
                new_st = str(item_b["status_code"]) if item_b.get("status_code") is not None else "連線失敗"
                if sec_downgraded:
                    new_err = "安全降級 (HTTPS ➔ HTTP)" + (f" ({new_err})" if new_err else "")
            else:
                st_a = f" ({item_a['status_code']})" if item_a.get("status_code") else ""
                st_b = f" ({item_b['status_code']})" if item_b.get("status_code") else ""
                old_st = f"HTTPS{st_a}"
                new_st = f"HTTP{st_b}"
                new_err = "安全降級 (HTTPS ➔ HTTP)"

            diff_lists["degraded"].append(
                {
                    "url": url,
                    "target_url": url,
                    "old_status": old_st,
                    "old_error": old_err,
                    "new_status": new_st,
                    "new_error": new_err,
                    "depth": item_b["depth"],
                }
            )
        # 2. 內部頁面復原 (Recovered)
        elif (a_bad and not b_bad) or (not a_bad and not b_bad and sec_upgraded):
            old_err = item_a["error"]
            new_err = item_b["error"]

            if a_bad and not b_bad:
                old_st = str(item_a["status_code"]) if item_a.get("status_code") is not None else "連線失敗"
                new_st = str(item_b["status_code"]) if item_b.get("status_code") is not None else "200"
                if sec_upgraded:
                    new_err = "安全升級 (HTTP ➔ HTTPS)"
            else:
                st_a = f" ({item_a['status_code']})" if item_a.get("status_code") else ""
                st_b = f" ({item_b['status_code']})" if item_b.get("status_code") else ""
                old_st = f"HTTP{st_a}"
                new_st = f"HTTPS{st_b}"
                new_err = "安全升級 (HTTP ➔ HTTPS)"

            diff_lists["recovered"].append(
                {
                    "url": url,
                    "target_url": url,
                    "old_status": old_st,
                    "old_error": old_err,
                    "new_status": new_st,
                    "new_error": new_err,
                    "depth": item_b["depth"],
                }
            )

    new_pages = [
        {
            "url": url,
            "target_url": url,
            "is_secure": dict_b[url]["is_secure"],
            "status_code": dict_b[url]["status_code"],
            "status_category": dict_b[url]["status_category"],
            "error": dict_b[url]["error"],
            "depth": dict_b[url]["depth"],
        }
        for url in (set_b - set_a)
    ]

    removed_pages = [
        {
            "url": url,
            "target_url": url,
            "old_is_secure": dict_a[url]["is_secure"],
            "old_status_code": dict_a[url]["status_code"],
            "old_status_category": dict_a[url]["status_category"],
            "old_error": dict_a[url]["error"],
            "depth": dict_a[url]["depth"],
        }
        for url in (set_a - set_b)
    ]

    summary = {
        "degraded": len(diff_lists["degraded"]),
        "recovered": len(diff_lists["recovered"]),
        "new_pages": len(new_pages),
        "removed_pages": len(removed_pages),
    }

    details = {
        "degraded": diff_lists["degraded"],
        "recovered": diff_lists["recovered"],
        "new_pages": new_pages,
        "removed_pages": removed_pages,
    }

    return summary, details


def get_job_diff(  # pylint: disable=too-many-arguments,too-many-locals
    db: DBSession,
    base_job_id: str,
    compare_job_id: str,
    user_id: str,
    exclude: str | None = None,
    scope: str = "all",
) -> dict[str, Any]:
    """
    比對兩個任務的歷史差異（支援外部連結、內部網頁或全選範疇）。

    根據基準任務 (Job A) 與對照任務 (Job B) 進行跨維度比對，產出包含外部連結異動與內部網頁
    健康度變遷的完整診斷結果與統計數據。

    Args:
        db (DBSession): Crawler DB Session。
        base_job_id (str): 基準任務 ID (舊任務)。
        compare_job_id (str): 對照任務 ID (新任務)。
        user_id (str): 請求查詢的使用者 ID。
        exclude (str | None): 要排除的目標網域，以逗號分隔。
        scope (str): 比對範疇，可選 'all'、'external' 或 'internal'，預設為 'all'。

    Returns:
        dict[str, Any]: 完整的歷史差異比對結果字典。

    Raises:
        ValueError: 當找不到指定 ID 的任務或使用者無權限存取該任務時拋出。
    """
    job_a = db.query(Job).filter(Job.id == base_job_id).first()
    job_b = db.query(Job).filter(Job.id == compare_job_id).first()

    if not job_a or (job_a.user_id or "") != (user_id or ""):
        raise ValueError(f"找不到基準任務 ID: {base_job_id}")
    if not job_b or (job_b.user_id or "") != (user_id or ""):
        raise ValueError(f"找不到對照任務 ID: {compare_job_id}")

    res: dict[str, Any] = {
        "base_job": {"id": job_a.id, "created_at": job_a.created_at.isoformat()},
        "compare_job": {"id": job_b.id, "created_at": job_b.created_at.isoformat()},
        "scope": scope,
    }

    # 1. 外部連結比對
    ext_dict_a = _build_external_dict_for_diff(db, base_job_id, exclude)
    ext_dict_b = _build_external_dict_for_diff(db, compare_job_id, exclude)
    ext_summary, ext_details = _compare_external_links(ext_dict_a, ext_dict_b)

    # 最外層保留原本的 summary 與 details，維護向上相容
    res["summary"] = ext_summary
    res["details"] = ext_details
    res["external"] = {"summary": ext_summary, "details": ext_details}

    # 2. 內部連結比對
    int_dict_a = _build_internal_dict_for_diff(db, base_job_id)
    int_dict_b = _build_internal_dict_for_diff(db, compare_job_id)
    int_summary, int_details = _compare_internal_links(int_dict_a, int_dict_b)

    res["internal"] = {"summary": int_summary, "details": int_details}

    return res
