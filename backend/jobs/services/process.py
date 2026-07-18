"""
底層進程與 PID 管理服務。

此模組提供了一系列與作業系統進程交互的輔助函式，主要職責如下：

- 負責 PID 檔案的建立、讀取與清理
- 透過 /proc/[pid]/stat 讀取進程啟動時間，防範 PID 循環重用誤判
- 驗證並監控爬蟲子進程 (Job Process) 是否仍在活躍狀態
- 實作節流機制 (Throttle) 以定期清理假死 (Zombie) 的任務與過期資源
"""

import logging
import os
import time
from datetime import datetime, timezone

from backend.jobs.constants import _ACTIVE_PROCESSES, PID_DIR
from crawler.manager import JobManager

logger: logging.Logger = logging.getLogger(__name__)

# 紀錄上一次執行清理動作的時間戳記 (由 time.time() 取得)
_LAST_CLEANUP_TIME: float = 0.0

# 殭屍任務與過期進程清理的時間節流區間 (秒)，避免高頻 API 呼叫拖垮磁碟 I/O
_CLEANUP_THROTTLE_SECONDS: float = 30.0


def _get_pid_file(job_id: str) -> str:
    """
    取得任務專屬的 PID 檔案路徑。

    Args:
        job_id (str): 任務 ID。

    Returns:
        str: PID 檔案路徑。
    """
    return os.path.join(PID_DIR, f"{job_id}.pid")


def _get_process_start_time(pid: int) -> str | None:
    """
    從 /proc/[pid]/stat 讀取進程的啟動時間 (starttime)，用於防止 PID 重用誤判。

    Args:
        pid (int): 欲查詢的進程 PID。

    Returns:
        str | None: 該進程的啟動時間字串（欄位值），若讀取失敗或進程不存在則回傳 None。
    """
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
            stat_content = f.read()

        # 尋找最後一個右括號，因為進程名稱可能包含空白
        rparen_idx = stat_content.rfind(")")
        if rparen_idx == -1:
            return None

        # 括號之後的欄位是以空白分隔的。括號本身是第 2 個欄位 (comm)，
        # 所以括號之後的第一個欄位 (state) 是第 3 個。
        # 啟動時間 (starttime) 在第 22 個欄位，對應分割後的 index 19。
        parts = stat_content[rparen_idx + 1 :].split()
        if len(parts) > 19:
            return parts[19]
    except OSError:
        pass
    return None


def _write_pid(job_id: str, pid: int) -> None:
    """
    將子進程 PID 與啟動時間寫入檔案。

    Args:
        job_id (str): 任務 ID。
        pid (int): 子程序 PID。
    """
    os.makedirs(PID_DIR, exist_ok=True)
    start_time = _get_process_start_time(pid) or ""
    with open(_get_pid_file(job_id), "w", encoding="utf-8") as f:
        f.write(f"{pid},{start_time}")


def _read_pid(job_id: str) -> tuple[int | None, str | None]:
    """
    讀取 PID 檔案中的 PID 與啟動時間。

    Args:
        job_id (str): 任務 ID。

    Returns:
        tuple[int | None, str | None]: 若有紀錄則回傳 (PID, start_time)，否則回傳 (None, None)。
    """
    pid_file = _get_pid_file(job_id)
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if "," in content:
                    pid_str, start_time = content.split(",", 1)
                    return int(pid_str), start_time if start_time else None
                return int(content), None
        except ValueError:
            pass
    return None, None


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


def _is_process_running(pid: int, expected_start_time: str | None = None) -> bool:
    """
    檢查系統中是否存在該 PID 的進程，並驗證啟動時間以防 PID 重用。

    Args:
        pid (int): 欲檢查的程序 PID。
        expected_start_time (str | None): 預期的進程啟動時間。

    Returns:
        bool: 若程序仍在執行且未被重用則回傳 True。
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        # 若提供了預期的啟動時間，則透過 /proc 進行比對驗證
        if expected_start_time:
            current_start_time = _get_process_start_time(pid)
            if current_start_time and current_start_time != expected_start_time:
                logger.warning(
                    "偵測到 PID %d 已被重用 (預期時間: %s, 實際時間: %s)", pid, expected_start_time, current_start_time
                )
                return False
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

    pid, expected_start_time = _read_pid(job_id)
    if pid is None:
        return False
    if _is_process_running(pid, expected_start_time):
        return True
    # PID 檔案存在但進程已死，順手清理
    _clear_pid(job_id)
    return False


def _cleanup_finished_processes() -> None:
    """
    清理所有已結束子程序的 PID 檔案，釋放過期資源。

    走訪 PID 目錄並檢查進程狀態，若已結束則清除對應 PID 檔。此函式內部具備節流機制，
    頻繁呼叫時會根據 `_CLEANUP_THROTTLE_SECONDS` 直接返回。
    """
    current_time = time.time()
    if current_time - _LAST_CLEANUP_TIME < _CLEANUP_THROTTLE_SECONDS:
        return

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
    global _LAST_CLEANUP_TIME  # pylint: disable=global-statement
    current_time = time.time()
    # 這裡的 throttle 確保即使從其他路徑單獨呼叫此函式，也不會頻繁觸發
    if current_time - _LAST_CLEANUP_TIME < _CLEANUP_THROTTLE_SECONDS:
        return
    _LAST_CLEANUP_TIME = current_time

    running_jobs = manager.get_all_jobs(status="running")
    for j in running_jobs:
        job_id = str(j["id"])
        if not _is_job_running(job_id):
            logger.warning("偵測到任務 %s 假死 (進程已不存在)，將狀態標記為 error (觸發來源: %s)", job_id, caller)
            manager.mark_job_error(job_id, "任務進程意外終止 (可能因系統 OOM 或伺服器重啟)")

    starting_jobs = manager.get_all_jobs(status="starting")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for j in starting_jobs:
        job_id = str(j["id"])
        try:
            updated_time = datetime.strptime(str(j["updated_at"]), "%Y-%m-%d %H:%M:%S")
            if (now - updated_time).total_seconds() > 30:
                if not _is_job_running(job_id):
                    logger.warning(
                        "偵測到任務 %s 在啟動階段假死 (進程已不存在)，將狀態標記為 error (觸發來源: %s)", job_id, caller
                    )
                    manager.mark_job_error(job_id, "任務啟動失敗 (子進程意外終止)")
        except ValueError as e:
            logger.debug("檢查 starting 任務 %s 時發生日期格式錯誤: %s", job_id, e)
