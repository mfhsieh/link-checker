"""
爬蟲報表匯出模組。

負責處理資料聚合、CSV/JSON 格式化、以及完整任務報表的 ZIP 匯出。
"""

import csv
import io
import json
import logging
import os
import zipfile
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.jobs.schemas import JobResultQuery
from backend.jobs.services import results as job_results
from crawler.models import CrawlQueue, ExternalLink, Job
from crawler.utils import format_crawl_queue_item

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class ExportOptions:
    """匯出結果的進階選項

    Attributes:
        status_filter (str | None): 狀態篩選條件。
        group_by (str): 聚合方式。
        exclude (str | None): 欲排除的網域。
    """

    status_filter: str | None = None
    group_by: str = "none"
    exclude: str | None = None


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


def _write_export_data(
    output_path: str, json_data: list[dict], csv_headers: list[str], csv_rows: list[list[object]]
) -> None:
    """將聚合後的資料寫入 JSON 或 CSV 檔案中

    Args:
        output_path (str): 輸出的檔案路徑。
        json_data (list[dict]): 要輸出的 JSON 格式資料。
        csv_headers (list[str]): CSV 的標頭欄位。
        csv_rows (list[list[object]]): CSV 的各列資料。
    """
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    is_json = output_path.lower().endswith(".json")
    if is_json:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
    else:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(csv_headers)
            writer.writerows(csv_rows)


def export_job_results(
    session_factory: Callable[[], Session],
    job_id: str,
    output_path: str,
    options: ExportOptions | None = None,
) -> bool:
    """
    將指定任務收集到的外部連結匯出為 CSV 或 JSON 格式。

    Args:
        session_factory (Callable[[], Session]): 資料庫 Session 工廠。
        job_id (str): 欲匯出結果的任務 ID。
        output_path (str): 匯出檔案的目的地路徑。
        options (ExportOptions | None): (選填) 進階匯出選項。

    Returns:
        bool: 匯出成功則回傳 True，發生錯誤或任務不存在回傳 False。
    """
    options = options or ExportOptions()

    with session_factory() as session:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("找不到指定的任務 ID: %s", job_id)
            return False

        try:
            query_obj = JobResultQuery(
                job_id=job_id,
                user_id=job.user_id,
                status_filter=options.status_filter,
                exclude=options.exclude,
                group_by=options.group_by,
                page=1,
                page_size=9999999,  # 匯出時一次取回所有資料
            )
            results = job_results.get_job_results(session, query_obj)
            items = results.get("items", [])
            if not items:
                logger.warning("任務 %s 無任何符合條件的結果可匯出。", job_id)
                return True

            _write_export_data(output_path, items, list(items[0].keys()), [list(item.values()) for item in items])
            return True
        except OSError as e:
            logger.error("匯出檔案時發生錯誤: %s", e)
            return False


def _export_crawl_records_to_zip(session: Session, job_id: str, zf: zipfile.ZipFile) -> None:
    """將爬取紀錄寫入 ZIP 壓縮檔中的 CSV

    Args:
        session (Session): 資料庫會話。
        job_id (str): 目標任務 ID。
        zf (zipfile.ZipFile): 目標 ZIP 壓縮檔物件。
    """
    q_count = session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).count()
    if q_count == 0:
        return

    q_items = session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).order_by(CrawlQueue.id).yield_per(2000)
    with zf.open(f"job_{job_id}_crawl_records.csv", "w") as f:
        with io.TextIOWrapper(f, encoding="utf-8-sig", newline="") as text_file:
            cq_writer = csv.writer(text_file)
            cq_writer.writerow([
                "Source URL",
                "URL",
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
                        d["Source URL"],
                        d["URL"],
                        d["Status"],
                        d["Depth"],
                        d["Retry Count"],
                        d["HTTP Status Code"],
                        d["Error Message"],
                        d["Created At"],
                    ])
                )


def _export_external_links_to_zip(session: Session, job_id: str, zf: zipfile.ZipFile) -> None:
    """將外部連結寫入 ZIP 壓縮檔中的 CSV

    Args:
        session (Session): 資料庫會話。
        job_id (str): 目標任務 ID。
        zf (zipfile.ZipFile): 目標 ZIP 壓縮檔物件。
    """
    e_count = session.query(ExternalLink).filter(ExternalLink.job_id == job_id).count()
    if e_count == 0:
        return

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


def export_full_report(
    session_factory: Callable[[], Session],
    job_id: str,
    output_path: str,
) -> bool:
    """
    匯出完整報表 (ZIP 壓縮檔)，內含爬取紀錄與外連清單。

    Args:
        session_factory (Callable[[], Session]): 資料庫 Session 工廠。
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

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                _export_crawl_records_to_zip(session, job_id, zf)
                _export_external_links_to_zip(session, job_id, zf)
            return True
        except OSError as e:
            logger.error("匯出完整報表時發生錯誤: %s", e)
            return False
