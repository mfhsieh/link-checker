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

# pylint: disable=too-many-lines

import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlparse
from sqlalchemy import func, case

from sqlalchemy.orm import Session as DBSession

from crawler.manager import JobManager
from crawler.exporter import format_crawl_queue_item
from crawler.models import CrawlQueue, ExternalLink, Job
from crawler.utils import (
    get_domain,
)

logger: logging.Logger = logging.getLogger(__name__)

PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PID_DIR: str = os.path.join(PROJECT_ROOT, "log", "pids")

# 新增一個全域變數來記錄 Web 程序 spawn 的爬蟲子進程
# 這樣我們就能呼叫 .poll() 來安全地回收 (Reap) 殭屍進程 (Zombie Processes)
_ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}


def _get_pid_file(job_id: str) -> str:
    """
    取得任務專屬的 PID 檔案路徑。

    Args:
        job_id (str): 任務 ID。

    Returns:
        str: PID 檔案路徑。
    """
    return os.path.join(PID_DIR, f"{job_id}.pid")


def _write_pid(job_id: str, pid: int) -> None:
    """
    將子進程 PID 寫入檔案。

    Args:
        job_id (str): 任務 ID。
        pid (int): 子程序 PID。
    """
    os.makedirs(PID_DIR, exist_ok=True)
    with open(_get_pid_file(job_id), "w", encoding="utf-8") as f:
        f.write(str(pid))


def _read_pid(job_id: str) -> int | None:
    """
    讀取 PID 檔案中的 PID。

    Args:
        job_id (str): 任務 ID。

    Returns:
        int | None: 若有紀錄則回傳 PID，否則回傳 None。
    """
    pid_file = _get_pid_file(job_id)
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except ValueError:
            pass
    return None


def _clear_pid(job_id: str) -> None:
    """
    清除 PID 檔案。

    Args:
        job_id (str): 任務 ID。
    """
    pid_file = _get_pid_file(job_id)
    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except OSError:
            pass


def _is_process_running(pid: int) -> bool:
    """
    檢查系統中是否存在該 PID 的進程。

    Args:
        pid (int): 欲檢查的程序 PID。

    Returns:
        bool: 若程序仍在執行則回傳 True。
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _is_job_running(job_id: str) -> bool:
    """
    檢查該任務的爬蟲子進程是否仍在運行中。

    Args:
        job_id (str): 任務 ID。

    Returns:
        bool: 若仍在運行中則回傳 True。
    """
    # 優先檢查本地記錄的 Popen 物件，透過 poll() 能自動回收殭屍進程
    proc = _ACTIVE_PROCESSES.get(job_id)
    if proc is not None:
        if proc.poll() is None:
            return True
        # 進程已結束，回收資源與 PID 檔案
        _ACTIVE_PROCESSES.pop(job_id, None)
        _clear_pid(job_id)
        return False

    pid = _read_pid(job_id)
    if pid is None:
        return False
    if _is_process_running(pid):
        return True
    # PID 檔案存在但進程已死，順手清理
    _clear_pid(job_id)
    return False


def _cleanup_finished_processes() -> None:
    """
    清理所有已結束子程序的 PID 檔案，釋放過期資源。

    走訪 PID 目錄並檢查進程狀態，若已結束則清除對應 PID 檔。
    """
    if not os.path.exists(PID_DIR):
        return
    for filename in os.listdir(PID_DIR):
        if filename.endswith(".pid"):
            job_id = filename[:-4]
            _is_job_running(job_id)


def _cleanup_zombie_jobs(manager: JobManager) -> None:
    """
    巡檢並清理假死任務 (Zombie Jobs)。
    若資料庫中狀態為 running，但本地已無對應的 PID 或進程，則將其標記為 error。

    Args:
        manager (JobManager): JobManager 實例。
    """
    running_jobs = manager.get_all_jobs(status="running")
    for j in running_jobs:
        job_id = j["id"]
        if not _is_job_running(job_id):
            logger.warning("偵測到任務 %s 假死 (進程已不存在)，將狀態標記為 error", job_id)
            manager.mark_job_error(job_id, "任務進程意外終止 (可能因系統 OOM 或伺服器重啟)")


@dataclass
class JobCreateConfig:
    """建立任務的設定封裝。"""

    start_url: str
    target_domains: list[str]
    trusted_domains: list[str]
    crawler_config: dict[str, object]


@dataclass
class JobResultQuery:
    """查詢任務結果的參數封裝。"""

    # pylint: disable=too-many-instance-attributes

    job_id: str
    user_id: str
    status_filter: str | None = None
    search: str | None = None
    exclude: str | None = None
    group_by: str = "none"
    page: int = 1
    page_size: int = 50


def create_job(
    manager: JobManager,
    user_id: str,
    config: JobCreateConfig,
) -> str:
    """
    建立新的爬蟲任務。

    Args:
        manager (JobManager): JobManager 實例。
        user_id (str): 任務擁有者 ID。
        config (JobCreateConfig): 新任務的設定選項。

    Returns:
        str: 建立成功的任務 ID。
    """
    job_id = manager.create_job(
        start_url=config.start_url,
        target_domains=config.target_domains,
        trusted_domains=config.trusted_domains,
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

    _cleanup_finished_processes()
    _cleanup_zombie_jobs(manager)
    if _is_job_running(job_id):
        raise ValueError("任務已在執行中。")

    cli_path = os.path.join(PROJECT_ROOT, "cli.py")

    try:
        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, cli_path, "--resume", job_id],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        _ACTIVE_PROCESSES[job_id] = proc
        _write_pid(job_id, proc.pid)
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


def get_job_detail(manager: JobManager, job_id: str, user_id: str | None = None) -> dict[str, object]:
    """
    取得任務詳情（含進度統計）。

    Args:
        manager (JobManager): JobManager 實例。
        job_id (str): 任務 ID。
        user_id (str | None): 若提供，驗證任務歸屬。

    Returns:
        dict[str, object]: 任務詳情與進度。
    """
    _cleanup_finished_processes()
    _cleanup_zombie_jobs(manager)

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
        "trusted_domains": (job.trusted_domains.split(",") if job.trusted_domains else []),
    }
    if job.config_json:
        try:
            raw_config = json.loads(job.config_json)
            allowed_keys = {
                "max_depth",
                "max_pages",
                "delay",
                "timeout",
                "connect_timeout",
                "external_check_timeout",
                "retries",
                "max_content_length",
                "max_redirects",
                "ignore_extensions",
                "ignore_regexes",
                "user_agent",
                "ssl_exempt_domains",
                "domain_delays",
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
        "is_running": _is_job_running(job_id),
        "ui_poll_interval": int(os.environ.get("UI_POLL_INTERVAL", 10000)),
    }


def list_jobs(manager: JobManager, user_id: str, status: str | None = None) -> list[dict[str, object]]:
    """
    列出指定使用者的所有任務。

    Args:
        manager (JobManager): JobManager 實例。
        user_id (str): 使用者 ID。
        status (str | None): 過濾狀態。

    Returns:
        list[dict[str, object]]: 任務摘要清單。
    """
    _cleanup_finished_processes()
    _cleanup_zombie_jobs(manager)

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


def transfer_job(manager: JobManager, job_id: str, user_id: str, target_user_id: str) -> bool:
    """
    移交任務給指定使用者。

    Args:
        manager (JobManager): JobManager 實例。
        job_id (str): 欲移交的任務 ID。
        user_id (str): 請求操作的使用者 ID。
        target_user_id (str): 接收任務的使用者 ID。

    Returns:
        bool: 成功回傳 True。

    Raises:
        ValueError: 無權限、任務不存在或任務正在執行中時拋出。
    """
    job = manager.get_job(job_id)
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if job.user_id != user_id:
        raise ValueError("無權限操作此任務。")
    if job.status == "running":
        raise ValueError("任務正在執行中，無法移交。請先暫停任務。")
    result = manager.transfer_job(job_id, target_user_id)
    if not result:
        raise ValueError("移交任務失敗，請確認任務狀態後再試。")
    return result


def reset_job(manager: JobManager, job_id: str, user_id: str) -> bool:
    """
    重置任務（清除佇列與外連，回到 pending 狀態）。執行中的任務無法重置。

    Args:
        manager (JobManager): JobManager 實例。
        job_id (str): 欲重置的任務 ID。
        user_id (str): 請求操作的使用者 ID。

    Returns:
        bool: 成功回傳 True。

    Raises:
        ValueError: 無權限、任務不存在或任務正在執行中時拋出。
    """
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


def retry_failed_job(manager: JobManager, job_id: str, user_id: str) -> bool:
    """
    局部重試任務（失敗項目歸零並回到 pending 狀態）。

    Args:
        manager (JobManager): JobManager 實例。
        job_id (str): 欲局部重試的任務 ID。
        user_id (str): 請求操作的使用者 ID。

    Returns:
        bool: 成功回傳 True。

    Raises:
        ValueError: 無權限、任務不存在或任務正在執行中時拋出。
    """
    job = manager.get_job(job_id)
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if job.user_id != user_id:
        raise ValueError("無權限操作此任務。")
    if job.status == "running":
        raise ValueError("任務正在執行中，無法直接重試，請先暫停任務。")
    result = manager.retry_failed_job(job_id)
    if not result:
        raise ValueError("重試任務失敗，請確認任務狀態後再試。")
    return result


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
        result.append({
            "domain": v["domain"],
            "occurrence_count": v["occurrence_count"],
            "unique_urls_count": len(v["unique_urls"]),
            "unique_urls": sorted(list(v["unique_urls"])),
        })
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
        d["targets"].append({
            "url": lnk.target_url,
            "status": status_str,
            "is_secure": lnk.is_secure,
            "error_message": lnk.error_message,
        })

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

    if query_args.search:
        search_pattern = f"%{query_args.search}%"
        query = query.filter(
            ExternalLink.target_url.like(search_pattern) | ExternalLink.source_url.like(search_pattern)
        )

    if query_args.exclude:
        excludes = [e.strip() for e in query_args.exclude.split(",") if e.strip()]
        for exc in excludes:
            query = query.filter(~ExternalLink.target_url.ilike(f"%{exc}%"))

    if query_args.status_filter == "dead":
        # dead：DNS 解析失敗（IP 位址為空）
        query = query.filter((ExternalLink.ip_address.is_(None)) | (ExternalLink.ip_address == ""))
    elif query_args.status_filter == "broken":
        # broken：HTTP 狀態碼 >= 400 或發生連線錯誤（無狀態碼但有 IP）
        query = query.filter(
            (ExternalLink.http_status_code >= 400)
            | (
                (ExternalLink.http_status_code.is_(None))
                & (ExternalLink.ip_address.isnot(None))
                & (ExternalLink.ip_address != "")
            )
        )
    elif query_args.status_filter == "insecure":
        # insecure：非 HTTPS (HTTP 明文傳輸)
        query = query.filter(ExternalLink.is_secure.is_(False))
    elif query_args.status_filter == "healthy":
        # healthy：解析成功且 HTTP 狀態碼小於 400
        query = query.filter(
            (ExternalLink.ip_address.isnot(None))
            & (ExternalLink.ip_address != "")
            & (ExternalLink.http_status_code.isnot(None))
            & (ExternalLink.http_status_code < 400)
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
    # pylint: disable=too-many-locals,too-many-branches
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if job.user_id != user_id:
        raise ValueError("無權限存取此任務。")

    total_queue = db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).count()

    if group_by == "none":
        # 透過單次聚合查詢大幅減少資料庫 I/O，優化百萬級外連任務的報表讀取效能
        # pylint: disable=not-callable
        query = db.query(
            func.count(ExternalLink.id).label("total"),
            func.sum(
                case(
                    (
                        (ExternalLink.ip_address.is_(None)) | (ExternalLink.ip_address == ""),
                        1,
                    ),
                    else_=0,
                )
            ).label("dns_failed"),
            func.sum(
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
            func.sum(case((ExternalLink.is_secure.is_(False), 1), else_=0)).label("insecure"),
        ).filter(ExternalLink.job_id == job_id)

        if exclude:
            excludes = [e.strip() for e in exclude.split(",") if e.strip()]
            for exc in excludes:
                query = query.filter(~ExternalLink.target_url.ilike(f"%{exc}%"))

        stats = query.first()
        # pylint: enable=not-callable

        total_external = int(stats.total) if stats and stats.total else 0
        dns_failed = int(stats.dns_failed) if stats and stats.dns_failed else 0
        http_errors = int(stats.http_errors) if stats and stats.http_errors else 0
        insecure = int(stats.insecure) if stats and stats.insecure else 0

        healthy_count = total_external - dns_failed - http_errors

    else:
        query = db.query(ExternalLink).filter(ExternalLink.job_id == job_id)
        if exclude:
            excludes = [e.strip() for e in exclude.split(",") if e.strip()]
            for exc in excludes:
                query = query.filter(~ExternalLink.target_url.ilike(f"%{exc}%"))

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

        total_external = len(set_all)
        dns_failed = len(set_dns_failed)
        http_errors = len(set_http_errors)
        insecure = len(set_insecure)
        healthy_count = len(set_healthy)

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
        d["sources"].add(lnk.source_url)  # pylint: disable=no-member
        d["is_secure"] = d["is_secure"] and lnk.is_secure
        if not d["ip"] and lnk.ip_address:
            d["ip"] = lnk.ip_address
        if d["status_code"] is None and lnk.http_status_code is not None:
            d["status_code"] = lnk.http_status_code
        if not d["error"] and lnk.error_message:
            d["error"] = lnk.error_message
    return dict(agg)


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
    # pylint: disable=too-many-locals
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

    added_urls = set_b - set_a
    removed_urls = set_a - set_b
    common_urls = set_a & set_b

    ip_changed = []
    degraded = []
    security_downgraded = []
    recovered = []

    def is_bad(item: dict[str, object]) -> bool:
        """
        判斷給定的外連項目是否處於異常/失效狀態。

        Args:
            item (dict[str, object]): 單筆外連統計項目字典。

        Returns:
            bool: 若 IP 解析失敗、HTTP 狀態碼異常或存在錯誤訊息，回傳 True。
        """
        if not item["ip"]:
            return True
        status_code = item["status_code"]
        if status_code is not None and int(str(status_code)) >= 400:
            return True
        if item["error"]:
            return True
        return False

    # pylint: disable=not-an-iterable
    for url in common_urls:
        item_a = dict_a[url]
        item_b = dict_b[url]

        # 1. IP Changed
        if item_a["ip"] and item_b["ip"] and item_a["ip"] != item_b["ip"]:
            ip_changed.append({
                "target_url": url,
                "old_ip": item_a["ip"],
                "new_ip": item_b["ip"],
                "sources": sorted(list(item_b["sources"])),
            })

        # 2. Security Downgraded
        if item_a["is_secure"] and not item_b["is_secure"]:
            security_downgraded.append({"target_url": url, "sources": sorted(list(item_b["sources"]))})

        # 3. Health status changed
        a_bad = is_bad(item_a)
        b_bad = is_bad(item_b)

        if not a_bad and b_bad:
            degraded.append({
                "target_url": url,
                "old_status": item_a["status_code"],
                "old_error": item_a["error"],
                "new_status": item_b["status_code"],
                "new_error": item_b["error"],
                "sources": sorted(list(item_b["sources"])),
            })
        elif a_bad and not b_bad:
            recovered.append({
                "target_url": url,
                "old_status": item_a["status_code"],
                "old_error": item_a["error"],
                "new_status": item_b["status_code"],
                "new_error": item_b["error"],
                "sources": sorted(list(item_b["sources"])),
            })

    new_links = []
    for url in added_urls:
        item = dict_b[url]
        new_links.append({
            "target_url": url,
            "ip": item["ip"],
            "status_code": item["status_code"],
            "error": item["error"],
            "sources": sorted(list(item["sources"])),
        })

    removed_links = []
    for url in removed_urls:
        item = dict_a[url]
        removed_links.append({
            "target_url": url,
            "old_ip": item["ip"],
            "old_status_code": item["status_code"],
            "old_error": item["error"],
            "sources": sorted(list(item["sources"])),
        })

    return {
        "base_job": {"id": job_a.id, "created_at": job_a.created_at.isoformat()},
        "compare_job": {"id": job_b.id, "created_at": job_b.created_at.isoformat()},
        "summary": {
            "ip_changed": len(ip_changed),
            "degraded": len(degraded),
            "security_downgraded": len(security_downgraded),
            "new_links": len(new_links),
            "removed_links": len(removed_links),
            "recovered": len(recovered),
        },
        "details": {
            "ip_changed": ip_changed,
            "degraded": degraded,
            "security_downgraded": security_downgraded,
            "new_links": new_links,
            "removed_links": removed_links,
            "recovered": recovered,
        },
    }


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
    # pylint: disable=too-many-branches
    job = db.query(Job).filter(Job.id == query_args.job_id).first()
    if not job or job.user_id != query_args.user_id:
        raise ValueError("無權限存取此任務。")

    query = db.query(ExternalLink).filter(ExternalLink.job_id == query_args.job_id)

    if query_args.status_filter == "dead":
        query = query.filter((ExternalLink.ip_address.is_(None)) | (ExternalLink.ip_address == ""))
    elif query_args.status_filter == "broken":
        query = query.filter(
            (ExternalLink.http_status_code >= 400)
            | (
                (ExternalLink.http_status_code.is_(None))
                & (ExternalLink.ip_address.isnot(None))
                & (ExternalLink.ip_address != "")
            )
        )
    elif query_args.status_filter == "insecure":
        query = query.filter(ExternalLink.is_secure.is_(False))
    elif query_args.status_filter == "healthy":
        query = query.filter(
            (ExternalLink.ip_address.isnot(None))
            & (ExternalLink.ip_address != "")
            & (ExternalLink.http_status_code.isnot(None))
            & (ExternalLink.http_status_code < 400)
        )

    if query_args.exclude:
        excludes = [e.strip() for e in query_args.exclude.split(",") if e.strip()]
        for exc in excludes:
            query = query.filter(~ExternalLink.target_url.ilike(f"%{exc}%"))

    # 使用 yield_per 每次只載入 2000 筆，避免 OOM
    cursor = query.order_by(ExternalLink.created_at).yield_per(2000)

    if query_args.group_by == "none":
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
    elif query_args.group_by == "target":
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
    elif query_args.group_by == "domain":
        agg = defaultdict(lambda: {"domain": "", "occurrence_count": 0, "unique_urls": set()})
        for lnk in cursor:
            dom = get_domain(lnk.target_url) or "unknown"
            d = agg[dom]
            d["domain"] = dom
            d["occurrence_count"] += 1
            d["unique_urls"].add(lnk.target_url)

        result = []
        for v in agg.values():
            result.append({
                "domain": v["domain"],
                "occurrence_count": v["occurrence_count"],
                "unique_urls_count": len(v["unique_urls"]),
                "unique_urls": sorted(list(v["unique_urls"])),
            })
        result.sort(key=lambda x: x["occurrence_count"], reverse=True)
        yield from result
    elif query_args.group_by == "source":
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
