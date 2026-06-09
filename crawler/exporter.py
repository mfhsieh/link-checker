"""
爬蟲報表匯出模組。

負責處理資料聚合、CSV/JSON 格式化、以及完整任務報表的 ZIP 匯出。
"""

# pylint: disable=unsubscriptable-object

import csv
import io
import json
import logging
import os
import zipfile
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy.orm import sessionmaker, Session

from crawler.models import CrawlQueue, ExternalLink, Job
from crawler.utils import get_domain

logger: logging.Logger = logging.getLogger(__name__)


def format_crawl_queue_item(q: CrawlQueue) -> dict[str, object]:
    """
    格式化 CrawlQueue 項目為字典供報表使用。

    Args:
        q (CrawlQueue): 欲格式化的佇列項目。

    Returns:
        dict[str, object]: 包含佇列項目詳細資訊的字典。
    """
    return {
        "URL": q.url,
        "Source URL": q.source_url if q.source_url else "",
        "Status": q.status,
        "Depth": q.depth,
        "Retry Count": q.retry_count,
        "HTTP Status Code": q.status_code if q.status_code is not None else "",
        "Error Message": q.error_message if q.error_message else "",
        "Created At": q.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _sanitize_csv_value(val: object) -> object:
    """
    跳脫 CSV 注入風險字元。

    Args:
        val (object): 原始數值。

    Returns:
        object: 跳脫後的安全數值。
    """
    if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@"):
        return f"'{val}"
    return val


def _sanitize_csv_row(row: list[object]) -> list[object]:
    """
    對 CSV 單行資料進行跳脫。

    Args:
        row (list[object]): 原始單行資料陣列。

    Returns:
        list[object]: 跳脫後的單行資料陣列。
    """
    return [_sanitize_csv_value(v) for v in row]


def _aggregate_by_target(
    links: Iterable[ExternalLink],
) -> tuple[list[dict[str, object]], list[str], list[list[object]]]:
    """
    依外部目標去重聚合，產出供匯出的 JSON 與 CSV 結構。

    Args:
        links (Iterable[ExternalLink]): 欲聚合的外部連結紀錄產生器或陣列。

    Returns:
        tuple[list[dict[str, object]], list[str], list[list[object]]]:
            (JSON 資料陣列, CSV 標頭, CSV 行資料陣列)。
    """
    agg_data = defaultdict(
        lambda: {
            "ip": "",
            "is_secure": True,
            "status_code": None,
            "error": "",
            "count": 0,
            "sources": set(),
        }
    )
    for link in links:
        tgt = link.target_url
        d = agg_data[tgt]
        d["count"] += 1
        d["sources"].add(link.source_url)
        d["is_secure"] = link.is_secure
        if link.ip_address and not d["ip"]:
            d["ip"] = link.ip_address
        if link.http_status_code is not None and d["status_code"] is None:
            d["status_code"] = link.http_status_code
        if link.error_message and not d["error"]:
            d["error"] = link.error_message

    json_data = []
    csv_rows = []
    csv_headers = [
        "Target URL",
        "IP Address",
        "Is Secure",
        "HTTP Status Code",
        "Error Message",
        "Occurrence Count",
        "Source URLs",
    ]

    for tgt, d in agg_data.items():
        sources_list = sorted(list(d["sources"]))
        json_data.append({
            "target_url": tgt,
            "ip_address": d["ip"] if d["ip"] else None,
            "is_secure": d["is_secure"],
            "http_status_code": d["status_code"],
            "error_message": d["error"] if d["error"] else None,
            "occurrence_count": d["count"],
            "source_urls": sources_list,
        })
        csv_rows.append(
            _sanitize_csv_row([
                tgt,
                d["ip"],
                d["is_secure"],
                d["status_code"] if d["status_code"] is not None else "",
                d["error"],
                d["count"],
                ", ".join(sources_list),
            ])
        )
    return json_data, csv_headers, csv_rows


def _aggregate_by_source(
    links: Iterable[ExternalLink],
) -> tuple[list[dict[str, object]], list[str], list[list[object]]]:
    """
    依自家網頁 (修補視角) 聚合，產出供匯出的 JSON 與 CSV 結構。

    Args:
        links (Iterable[ExternalLink]): 欲聚合的外部連結紀錄產生器或陣列。

    Returns:
        tuple[list[dict[str, object]], list[str], list[list[object]]]:
            (JSON 資料陣列, CSV 標頭, CSV 行資料陣列)。
    """
    agg_source = defaultdict(lambda: {"count": 0, "targets": []})
    for link in links:
        d = agg_source[link.source_url]
        d["count"] += 1
        status_str = (
            str(link.http_status_code)
            if link.http_status_code is not None
            else ("DNS Failed" if not link.ip_address else "Error")
        )
        d["targets"].append({"url": link.target_url, "status": status_str})

    json_data = []
    csv_rows = []
    csv_headers = ["Source URL", "Occurrence Count", "Target URLs"]
    for src, d in agg_source.items():
        json_data.append({"source_url": src, "occurrence_count": d["count"], "targets": d["targets"]})
        targets_str = "\n".join([f"[{t['status']}] {t['url']}" for t in d["targets"]])
        csv_rows.append(_sanitize_csv_row([src, d["count"], targets_str]))

    return json_data, csv_headers, csv_rows


def _aggregate_by_domain(
    links: Iterable[ExternalLink],
) -> tuple[list[dict[str, object]], list[str], list[list[object]]]:
    """
    依外部網域聚合 (資安盤點)，產出供匯出的 JSON 與 CSV 結構。

    Args:
        links (Iterable[ExternalLink]): 欲聚合的外部連結紀錄產生器或陣列。

    Returns:
        tuple[list[dict[str, object]], list[str], list[list[object]]]:
            (JSON 資料陣列, CSV 標頭, CSV 行資料陣列)。
    """
    agg_domain: dict[str, dict[str, object]] = defaultdict(lambda: {"count": 0, "urls": set()})
    for link in links:
        dom = get_domain(link.target_url) or "unknown"
        d = agg_domain[dom]
        d["count"] += 1
        d["urls"].add(link.target_url)

    sorted_domains = sorted(agg_domain.items(), key=lambda x: x[1]["count"], reverse=True)

    json_data = []
    csv_rows = []
    csv_headers = ["Domain", "Occurrence Count", "Unique URLs Count", "Unique URLs"]

    for dom, d in sorted_domains:
        urls_sorted = sorted(list(d["urls"]))
        json_data.append({
            "domain": dom,
            "occurrence_count": d["count"],
            "unique_urls_count": len(d["urls"]),
            "unique_urls": urls_sorted,
        })
        urls_str = "\n".join(urls_sorted)
        csv_rows.append(_sanitize_csv_row([dom, d["count"], len(d["urls"]), urls_str]))

    return json_data, csv_headers, csv_rows


def _format_no_grouping(
    links: Iterable[ExternalLink],
) -> tuple[list[dict[str, object]], list[str], list[list[object]]]:
    """
    平鋪導出 (不聚合)，產出供匯出的 JSON 與 CSV 結構。

    Args:
        links (Iterable[ExternalLink]): 欲轉換的外部連結紀錄產生器或陣列。

    Returns:
        tuple[list[dict[str, object]], list[str], list[list[object]]]:
            (JSON 資料陣列, CSV 標頭, CSV 行資料陣列)。
    """
    json_data = []
    csv_rows = []
    csv_headers = [
        "Source URL",
        "Target URL",
        "IP Address",
        "Is Secure",
        "HTTP Status Code",
        "Error Message",
        "Found At",
    ]
    for link in links:
        json_data.append({
            "source_url": link.source_url,
            "target_url": link.target_url,
            "ip_address": link.ip_address if link.ip_address else None,
            "is_secure": link.is_secure,
            "http_status_code": link.http_status_code,
            "error_message": link.error_message if link.error_message else None,
            "created_at": link.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })
        csv_rows.append(
            _sanitize_csv_row([
                link.source_url,
                link.target_url,
                link.ip_address if link.ip_address else "",
                link.is_secure,
                link.http_status_code if link.http_status_code is not None else "",
                link.error_message if link.error_message else "",
                link.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            ])
        )
    return json_data, csv_headers, csv_rows


def export_job_results(
    session_factory: sessionmaker[Session],
    job_id: str,
    output_path: str,
    status_filter: str | None = None,
    export_group: bool = False,
    group_by: str = "none",
    exclude: str | None = None,
) -> bool:
    """
    將指定任務收集到的外部連結匯出為 CSV 或 JSON 格式。

    Args:
        session_factory (sessionmaker[Session]): 資料庫 Session 工廠。
        job_id (str): 欲匯出結果的任務 ID。
        output_path (str): 匯出檔案的目的地路徑。
        status_filter (str | None): (選填) 'dead', 'broken' 或 'insecure' 的過濾條件。
        export_group (bool): (已棄用) 向下相容，請改用 group_by="target"。
        group_by (str): 聚合模式 ("none", "target", "source", "domain")。
        exclude (str | None): (選填) 排除指定的目標網域，多個以逗號分隔。

    Returns:
        bool: 匯出成功則回傳 True，發生錯誤或任務不存在回傳 False。
    """
    with session_factory() as session:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("找不到指定的任務 ID: %s", job_id)
            return False

        query = session.query(ExternalLink).filter(ExternalLink.job_id == job_id)

        if status_filter == "dead":
            query = query.filter((ExternalLink.ip_address.is_(None)) | (ExternalLink.ip_address == ""))
        elif status_filter == "broken":
            query = query.filter(
                (ExternalLink.http_status_code >= 400)
                | (
                    (ExternalLink.http_status_code.is_(None))
                    & (ExternalLink.ip_address.isnot(None))
                    & (ExternalLink.ip_address != "")
                )
            )
        elif status_filter == "insecure":
            query = query.filter(ExternalLink.is_secure.is_(False))

        if exclude:
            excludes = [e.strip() for e in exclude.split(",") if e.strip()]
            for exc in excludes:
                query = query.filter(~ExternalLink.target_url.ilike(f"%{exc}%"))

        links = query.order_by(ExternalLink.created_at).yield_per(2000)

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        is_json = output_path.lower().endswith(".json")

        try:
            if export_group and group_by == "none":
                group_by = "target"

            if group_by == "target":
                json_data, csv_headers, csv_rows = _aggregate_by_target(links)
            elif group_by == "source":
                json_data, csv_headers, csv_rows = _aggregate_by_source(links)
            elif group_by == "domain":
                json_data, csv_headers, csv_rows = _aggregate_by_domain(links)
            else:
                json_data, csv_headers, csv_rows = _format_no_grouping(links)

            if is_json:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(json_data, f, ensure_ascii=False, indent=2)
            else:
                with open(output_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(csv_headers)
                    writer.writerows(csv_rows)

            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("匯出檔案時發生錯誤: %s", e)
            return False


def export_full_report(session_factory: sessionmaker[Session], job_id: str, output_path: str) -> bool:
    """
    匯出完整報表 (ZIP 壓縮檔)，內含爬取紀錄與外連清單。

    Args:
        session_factory (sessionmaker[Session]): 資料庫 Session 工廠。
        job_id (str): 欲匯出完整報表的任務 ID。
        output_path (str): 輸出的 ZIP 檔案路徑。

    Returns:
        bool: 匯出成功回傳 True，發生錯誤或任務不存在回傳 False。
    """
    with session_factory() as session:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("找不到指定的任務 ID: %s", job_id)
            return False

        q_count = session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).count()
        e_count = session.query(ExternalLink).filter(ExternalLink.job_id == job_id).count()

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if q_count > 0:
                    q_items = (
                        session
                        .query(CrawlQueue)
                        .filter(CrawlQueue.job_id == job_id)
                        .order_by(CrawlQueue.id)
                        .yield_per(2000)
                    )
                    with zf.open(f"job_{job_id}_crawl_records.csv", "w") as f:
                        with io.TextIOWrapper(f, encoding="utf-8-sig", newline="") as text_file:
                            cq_writer = csv.writer(text_file)
                            cq_writer.writerow([
                                "URL",
                                "Source URL",
                                "Status",
                                "Depth",
                                "Retry Count",
                                "HTTP Status Code",
                                "Error Message",
                                "Created At",
                            ])
                            for q in q_items:
                                d = format_crawl_queue_item(q)
                                cq_writer.writerow(
                                    _sanitize_csv_row([
                                        d["URL"],
                                        d["Source URL"],
                                        d["Status"],
                                        d["Depth"],
                                        d["Retry Count"],
                                        d["HTTP Status Code"],
                                        d["Error Message"],
                                        d["Created At"],
                                    ])
                                )

                if e_count > 0:
                    e_items = (
                        session
                        .query(ExternalLink)
                        .filter(ExternalLink.job_id == job_id)
                        .order_by(ExternalLink.created_at)
                        .yield_per(2000)
                    )
                    with zf.open(f"job_{job_id}_external_links.csv", "w") as f:
                        with io.TextIOWrapper(f, encoding="utf-8-sig", newline="") as text_file:
                            el_writer = csv.writer(text_file)
                            el_writer.writerow([
                                "Source URL",
                                "Target URL",
                                "IP Address",
                                "Is Secure",
                                "HTTP Status Code",
                                "Error Message",
                                "Found At",
                            ])
                            for link in e_items:
                                el_writer.writerow(
                                    _sanitize_csv_row([
                                        link.source_url,
                                        link.target_url,
                                        link.ip_address if link.ip_address else "",
                                        link.is_secure,
                                        link.http_status_code if link.http_status_code is not None else "",
                                        link.error_message if link.error_message else "",
                                        link.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                                    ])
                                )
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("匯出完整報表時發生錯誤: %s", e)
            return False
