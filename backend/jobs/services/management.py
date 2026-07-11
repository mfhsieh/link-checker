"""
任務管理核心邏輯。
"""

import json
import logging
import os
import subprocess
import sys
from urllib.parse import urlparse

from backend.jobs.constants import _ACTIVE_PROCESSES, ALLOWED_CRAWLER_CONFIG_KEYS, PROJECT_ROOT
from backend.jobs.schemas import JobCreateConfig
from backend.jobs.services.process import _cleanup_finished_processes, _cleanup_zombie_jobs, _is_job_running, _write_pid
from crawler.manager import JobCreateOptions, JobManager
from crawler.models import Job

logger: logging.Logger = logging.getLogger(__name__)


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
        JobCreateOptions(
            start_url=config.start_url,
            target_domains=config.target_domains,
            trusted_domains=config.trusted_domains,
            crawler_config=config.crawler_config,
            user_id=user_id,
        )
    )
    logger.info("使用者 %s 建立新任務 %s，起始 URL: %s", user_id, job_id, config.start_url)
    return job_id


def start_job(manager: JobManager, job_id: str, user_id: str | None = None) -> bool:
    """
    啟動指定任務：以 Subprocess 方式 spawn 爬蟲子程序。

    子程序執行 `python cli.py --resume <job_id>`，
    讀取任務的 config_json 快照並開始爬取。
    若目前執行中的任務數達到上限，則狀態轉為 `queued` 並暫不啟動子程序。

    Args:
        manager (JobManager): JobManager 實例。
        job_id (str): 欲啟動的任務 ID。
        user_id (str | None): 請求啟動的使用者 ID（用於授權驗證，None 代表系統排程器）。

    Returns:
        bool: 啟動指令已發送或已進入排隊則回傳 True。

    Raises:
        ValueError: 任務不存在、不屬於該使用者，或狀態不允許啟動。
    """
    job = manager.get_job(job_id)
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if user_id is not None and job.user_id != user_id:
        raise ValueError("無權限操作此任務。")
    if job.status not in ("pending", "paused", "error", "queued"):
        raise ValueError(f"任務目前狀態為 {job.status}，無法啟動。")

    _cleanup_finished_processes()
    _cleanup_zombie_jobs(manager, caller="start_job")
    if _is_job_running(job_id):
        raise ValueError("任務已在執行中。")

    from backend.config import get_settings  # pylint: disable=import-outside-toplevel

    max_concurrent = get_settings().CRAWLER_MAX_CONCURRENT_JOBS

    with manager.session_factory() as session:
        # 若為使用者主動發起的啟動，需檢查並發上限，可能需轉入排隊
        if user_id is not None and max_concurrent > 0:
            active_count = session.query(Job).filter(Job.status.in_(["starting", "running"])).count()
            if active_count >= max_concurrent:
                # 使用樂觀鎖（條件式 UPDATE）確保原子性更新
                # 避免多個並發請求同時通過 PID 與狀態檢查，導致同一個任務被 Spawn 兩次
                updated = (
                    session.query(Job)
                    .filter(Job.id == job_id, Job.status.in_(["pending", "paused", "error", "queued"]))
                    .update({"status": "queued"}, synchronize_session=False)
                )
                session.commit()
                if updated == 0:
                    raise ValueError("任務狀態已被其他請求搶先修改，請重試。")
                logger.info("任務 %s 進入排隊狀態 (目前執行中: %d, 上限: %d)", job_id, active_count, max_concurrent)
                return True

        # 若未達上限或為排程器發起 (user_id=None)，則進入 starting
        # 同樣使用樂觀鎖確保原子性，防止 Race Condition 導致雙重 Spawn
        updated = (
            session.query(Job)
            .filter(Job.id == job_id, Job.status.in_(["pending", "paused", "error", "queued"]))
            .update({"status": "starting"}, synchronize_session=False)
        )
        session.commit()
        if updated == 0:
            raise ValueError("任務狀態已被其他請求搶先修改，請重試。")

    cli_path = os.path.join(PROJECT_ROOT, "cli.py")

    try:
        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, cli_path, "--api-spawn", job_id],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        _ACTIVE_PROCESSES[job_id] = proc
        _write_pid(job_id, proc.pid)
        logger.info("任務 %s 已啟動（PID: %d）", job_id, proc.pid)
        return True
    except Exception as e:
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


def get_job_detail(manager: JobManager, job_id: str, user_id: str, *, bypass_auth: bool = False) -> dict[str, object]:
    """
    取得任務詳情（含進度統計）。

    Args:
        manager (JobManager): JobManager 實例。
        job_id (str): 任務 ID。
        user_id (str): 驗證任務歸屬。若為系統內部輪詢，可傳入任意字串配合 bypass_auth=True。
        bypass_auth (bool): 若為 True 則略過歸屬驗證（僅限系統內部背景服務使用）。

    Returns:
        dict[str, object]: 任務詳情與進度。
    """
    _cleanup_finished_processes()
    _cleanup_zombie_jobs(manager, caller="get_job_detail")

    job = manager.get_job(job_id)
    if not job:
        raise ValueError(f"找不到任務 ID: {job_id}")
    if not bypass_auth and job.user_id != user_id:
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
            allowed_keys = ALLOWED_CRAWLER_CONFIG_KEYS
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
    _cleanup_zombie_jobs(manager, caller="list_jobs")

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
    if job.status in ("running", "starting"):
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
    if job.status in ("running", "starting", "queued"):
        raise ValueError("任務正在執行或排隊中，無法直接重置，請先暫停任務。")
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
    if job.status in ("running", "starting", "queued"):
        raise ValueError("任務正在執行或排隊中，無法直接重試，請先暫停任務。")
    result = manager.retry_failed_job(job_id)
    if not result:
        raise ValueError("重試任務失敗，請確認任務狀態後再試。")
    return result
