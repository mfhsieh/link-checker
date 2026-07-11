"""
底層進程與 PID 管理服務。
"""

import logging
import os
from datetime import datetime, timezone
from typing import cast

from backend.jobs.constants import _ACTIVE_PROCESSES, PID_DIR
from crawler.manager import JobManager

logger: logging.Logger = logging.getLogger(__name__)


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


def _cleanup_zombie_jobs(manager: JobManager, caller: str = "unknown") -> None:
    """
    巡檢並清理假死任務 (Zombie Jobs)。
    若資料庫中狀態為 running，但本地已無對應的 PID 或進程，則將其標記為 error。

    Args:
        manager (JobManager): JobManager 實例。
        caller (str): 觸發來源，用於日誌追蹤。
    """
    running_jobs = manager.get_all_jobs(status="running")
    for j in running_jobs:
        job_id = cast(str, j["id"])
        if not _is_job_running(job_id):
            logger.warning("偵測到任務 %s 假死 (進程已不存在)，將狀態標記為 error (觸發來源: %s)", job_id, caller)
            manager.mark_job_error(job_id, "任務進程意外終止 (可能因系統 OOM 或伺服器重啟)")

    starting_jobs = manager.get_all_jobs(status="starting")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for j in starting_jobs:
        job_id = cast(str, j["id"])
        try:
            updated_time = datetime.strptime(cast(str, j["updated_at"]), "%Y-%m-%d %H:%M:%S")
            if (now - updated_time).total_seconds() > 30:
                if not _is_job_running(job_id):
                    logger.warning(
                        "偵測到任務 %s 在啟動階段假死 (進程已不存在)，將狀態標記為 error (觸發來源: %s)", job_id, caller
                    )
                    manager.mark_job_error(job_id, "任務啟動失敗 (子進程意外終止)")
        except ValueError as e:
            logger.debug("檢查 starting 任務 %s 時發生日期格式錯誤: %s", job_id, e)
