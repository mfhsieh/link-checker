"""
任務管理業務邏輯服務模組。

橋接現有的 crawler/manager.py 與 Web API 層，
透過 Subprocess 模式啟動爬蟲子程序，實作任務的全生命週期管理。

程序模型（§12.1）：
- 任務建立後不自動啟動（status=pending）
- 使用者點擊啟動後，Web 服務 spawn 爬蟲子程序
- Web 服務不阻塞等待，透過輪詢 Crawler DB 取得進度
- 暫停透過更新 DB 狀態為 paused 觸發（爬蟲迴圈偵測後安全終止）
"""

import json
import logging
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session as DBSession

from crawler.manager import JobManager
from crawler.models import CrawlQueue, ExternalLink, Job
from crawler.utils import (
    get_domain,
    is_in_domain_list,
    get_approved_domains_from_config,
)

logger = logging.getLogger(__name__)

# 記錄正在執行中的爬蟲子程序 PID（記憶體內，程序重啟後清失）
_running_processes: dict[str, subprocess.Popen] = {}


@dataclass
class JobCreateConfig:
    """建立任務的設定封裝。"""
    start_url: str
    target_domains: list[str]
    internal_domains: list[str]
    crawler_config: dict[str, Any]


@dataclass
class JobResultQuery:
    """查詢任務結果的參數封裝。"""
    job_id: str
    user_id: str
    status_filter: str | None = None
    search: str | None = None
    group: bool = False
    page: int = 1
    page_size: int = 50


def create_job(
    manager: JobManager,
    user_id: str,
    config: JobCreateConfig,
) -> str:
    """建立新的爬蟲任務。"""
    job_id = manager.create_job(
        start_url=config.start_url,
        target_domains=config.target_domains,
        internal_domains=config.internal_domains,
        crawler_config=config.crawler_config,
        user_id=user_id,
    )
    logger.info("使用者 %s 建立新任務 %s，起始 URL: %s", user_id, job_id, config.start_url)
    return job_id


def start_job(manager: JobManager, job_id: str, user_id: str) -> bool:
    """
    啟動指定任務：以 Subprocess 方式 spawn 爬蟲子程序。

    子程序執行 `python cli.py --resume <job_id>`，
    讀取任務的 config_json 快照並開始爬取。

    Args:
        manager (JobManager): JobManager 實例。
        job_id (str): 欲啟動的任務 ID。
        user_id (str): 請求啟動的使用者 ID（用於授權驗證）。

    Returns:
        bool: 啟動成功回傳 True。

    Raises:
        ValueError: 任務不存在、不屬於該使用者，或狀態不允許啟動。
    """
    job = manager.get_job(job_id)
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if job.user_id != user_id:
        raise ValueError("無權限操作此任務。")
    if job.status not in ("pending", "paused"):
        raise ValueError(f"任務目前狀態為 {job.status}，無法啟動。")

    if job_id in _running_processes and _running_processes[job_id].poll() is None:
        raise ValueError("任務已在執行中。")

    # 取得專案根目錄的 cli.py 路徑
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cli_path = os.path.join(project_root, "cli.py")

    try:
        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, cli_path, "--resume", job_id],
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        _running_processes[job_id] = proc
        logger.info("任務 %s 已啟動（PID: %d）", job_id, proc.pid)
        return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("啟動任務 %s 失敗: %s", job_id, e)
        raise ValueError(f"啟動爬蟲子程序時發生錯誤: {e}") from e


def pause_job(manager: JobManager, job_id: str, user_id: str) -> bool:
    """
    暫停指定任務：更新 DB 狀態為 paused。

    爬蟲迴圈在下一次迭代開始前會檢查任務狀態，
    若狀態不為 running 則安全終止，實現協同暫停。

    Args:
        manager (JobManager): JobManager 實例。
        job_id (str): 欲暫停的任務 ID。
        user_id (str): 請求暫停的使用者 ID。

    Returns:
        bool: 暫停指令已發送回傳 True。
    """
    job = manager.get_job(job_id)
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if job.user_id != user_id:
        raise ValueError("無權限操作此任務。")

    result = manager.pause_job(job_id)
    if result:
        logger.info("任務 %s 暫停指令已發送（協同暫停）", job_id)
    return result


def get_job_detail(manager: JobManager, job_id: str, user_id: str | None = None) -> dict[str, Any]:
    """
    取得任務詳情（含進度統計）。

    Args:
        manager (JobManager): JobManager 實例。
        job_id (str): 任務 ID。
        user_id (str | None): 若提供，驗證任務歸屬。

    Returns:
        dict: 任務詳情與進度。
    """
    job = manager.get_job(job_id)
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if user_id is not None and job.user_id != user_id:
        raise ValueError("無權限存取此任務。")

    report = manager.get_job_report(job_id)
    if not report:
        raise ValueError("無法取得任務報告。")

    # 組合一份只包含「使用者需要知道的」安全設定快照
    config_snapshot = {
        "target_domains": job.target_domains.split(",") if job.target_domains else [],
        "internal_domains": job.internal_domains.split(",") if job.internal_domains else [],
    }
    if job.config_json:
        try:
            raw_config = json.loads(job.config_json)
            allowed_keys = {
                "max_depth", "max_pages", "delay", "timeout",
                "retries", "ignore_extensions", "ignore_regexes", "approved_domains"
            }
            for k in allowed_keys:
                if k in raw_config:
                    config_snapshot[k] = raw_config[k]
            
            if raw_config.get("proxy_url"):
                parsed = urlparse(raw_config["proxy_url"])
                if parsed.password:
                    config_snapshot["proxy_url"] = raw_config["proxy_url"].replace(parsed.password, "***")
                else:
                    config_snapshot["proxy_url"] = raw_config["proxy_url"]
        except json.JSONDecodeError:
            pass

    return {
        "id": job.id,
        "start_url": job.start_url,
        "status": job.status,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "config": config_snapshot,
        "progress": report["queue"],
        "external_link_count": report["external_links"],
        "is_running": (
            job_id in _running_processes
            and _running_processes[job_id].poll() is None
        ),
        "ui_poll_interval": int(os.environ.get("UI_POLL_INTERVAL", 10000)),
    }


def list_jobs(manager: JobManager, user_id: str, status: str | None = None) -> list[dict[str, Any]]:
    """
    列出指定使用者的所有任務。

    Args:
        manager (JobManager): JobManager 實例。
        user_id (str): 使用者 ID。
        status (str | None): 過濾狀態。

    Returns:
        list[dict]: 任務摘要清單。
    """
    return manager.get_all_jobs(user_id=user_id, status=status)


def delete_job(manager: JobManager, job_id: str, user_id: str) -> bool:
    """
    刪除任務及其所有相關資料。

    Args:
        manager (JobManager): JobManager 實例。
        job_id (str): 欲刪除的任務 ID。
        user_id (str): 請求刪除的使用者 ID。

    Returns:
        bool: 刪除成功回傳 True。
    """
    job = manager.get_job(job_id)
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if job.user_id != user_id:
        raise ValueError("無權限刪除此任務。")

    return manager.delete_job(job_id)


def reset_job(manager: JobManager, job_id: str, user_id: str) -> bool:
    """重置任務（清除佇列與外連，回到 pending 狀態）。執行中的任務無法重置。"""
    job = manager.get_job(job_id)
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if job.user_id != user_id:
        raise ValueError("無權限重置此任務。")
    if job.status == "running":
        raise ValueError("任務正在執行中，無法直接重置，請先暫停任務。")
    result = manager.reset_job(job_id)
    if not result:
        raise ValueError("重置任務失敗，請確認任務狀態後再試。")
    return result


def _group_results(links: list[ExternalLink]) -> list[dict[str, Any]]:
    """將結果去重聚合。"""
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "target_url": "",
        "ip_address": None,
        "is_secure": True,
        "http_status_code": None,
        "error_message": None,
        "occurrence_count": 0,
        "source_urls": set(),
    })
    for lnk in links:
        d = agg[lnk.target_url]
        d["target_url"] = lnk.target_url
        d["occurrence_count"] += 1
        d["source_urls"].add(lnk.source_url)
        d["is_secure"] = lnk.is_secure
        if not d["ip_address"] and lnk.ip_address:
            d["ip_address"] = lnk.ip_address
        if d["http_status_code"] is None and lnk.http_status_code is not None:
            d["http_status_code"] = lnk.http_status_code
        if not d["error_message"] and lnk.error_message:
            d["error_message"] = lnk.error_message

    return [
        {**v, "source_urls": sorted(list(v["source_urls"]))}
        for v in agg.values()
    ]


def _filter_unapproved_links(links: list[ExternalLink], job: Job) -> list[ExternalLink]:
    """過濾出未核准的外部連結。"""
    approved_domains = get_approved_domains_from_config(job.config_json)
    filtered = []
    for lnk in links:
        domain = get_domain(lnk.target_url) or ""
        if not is_in_domain_list(domain, approved_domains):
            filtered.append(lnk)
    return filtered


def get_job_results(
    db: DBSession,
    query_args: JobResultQuery,
) -> dict[str, Any]:
    """查詢任務的外連結果，支援篩選、搜尋、去重聚合與分頁。"""
    job = db.query(Job).filter(Job.id == query_args.job_id).first()
    if not job:
        raise ValueError(f"找不到任務 ID: {query_args.job_id}")
    if job.user_id != query_args.user_id:
        raise ValueError("無權限存取此任務。")

    query = db.query(ExternalLink).filter(ExternalLink.job_id == query_args.job_id)

    if query_args.search:
        search_pattern = f"%{query_args.search}%"
        query = query.filter(
            ExternalLink.target_url.like(search_pattern)
            | ExternalLink.source_url.like(search_pattern)
        )

    if query_args.status_filter == "dead":
        # dead：DNS 解析失敗（IP 位址為空）
        query = query.filter((ExternalLink.ip_address.is_(None)) | (ExternalLink.ip_address == ""))
    elif query_args.status_filter == "broken":
        # broken：有 HTTP 回應但狀態碼 >= 400（不含 NULL，NULL 屬於連線錯誤/尚未探測）
        query = query.filter(ExternalLink.http_status_code >= 400)

    links = query.order_by(ExternalLink.created_at).all()

    if query_args.status_filter == "unapproved":
        # 注意：unapproved 篩選需在 Python 層全量載入後過濾（無法下推至 SQL）
        # 當外連數量龐大時（> 10000 筆）效能可能較差
        if len(links) > 10000:
            logger.warning(
                "任務 %s 的 unapproved 篩選需載入 %d 筆外連記錄，可能較緩慢。",
                query_args.job_id, len(links)
            )
        links = _filter_unapproved_links(links, job)

    if query_args.group:
        items_list = _group_results(links)
    else:
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

    total = len(items_list)
    offset = (query_args.page - 1) * query_args.page_size
    items = items_list[offset: offset + query_args.page_size]

    # 計算總頁數
    total_pages = (total + query_args.page_size - 1) // query_args.page_size if total > 0 else 1

    return {
        "items": items,
        "total": total,
        "page": query_args.page,
        "page_size": query_args.page_size,
        "total_pages": total_pages,
    }


def get_results_summary(db: DBSession, job_id: str, user_id: str) -> dict[str, Any]:
    """取得任務結果的統計摘要。"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if job.user_id != user_id:
        raise ValueError("無權限存取此任務。")

    total_queue = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).count()
    total_external = db.query(ExternalLink).filter(ExternalLink.job_id == job_id).count()
    dns_failed = db.query(ExternalLink).filter(
        ExternalLink.job_id == job_id,
        (ExternalLink.ip_address.is_(None)) | (ExternalLink.ip_address == ""),
    ).count()
    http_errors = db.query(ExternalLink).filter(
        ExternalLink.job_id == job_id,
        ExternalLink.http_status_code >= 400,
    ).count()
    insecure = db.query(ExternalLink).filter(
        ExternalLink.job_id == job_id,
        ExternalLink.is_secure.is_(False),
    ).count()

    return {
        "job_id": job_id,
        "total_crawled_pages": total_queue,
        "total_external_links": total_external,
        "dns_failed_count": dns_failed,
        "http_error_count": http_errors,
        "insecure_count": insecure,
    }
