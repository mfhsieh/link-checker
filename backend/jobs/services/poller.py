"""
集中式的任務進度輪詢器。

將高併發的 SSE 資料庫輪詢請求收攏為單一背景任務，
以 O(1) 的頻率查詢資料庫後，透過 Event Bus 廣播給所有訂閱的客戶端。
"""

import asyncio
import json
import logging
from typing import Dict

from fastapi.concurrency import run_in_threadpool

from backend.deps import get_job_manager
from backend.events import publish
from backend.jobs.services import management as job_management

logger: logging.Logger = logging.getLogger(__name__)


class JobProgressPoller:
    """
    任務進度輪詢器。

    維持一個背景迴圈，定期針對活躍的任務 ID 查詢最新進度，
    並透過事件匯流排廣播，降低資料庫存取壓力。
    """

    def __init__(self) -> None:
        """
        初始化任務進度輪詢器。
        
        建立用來追蹤活躍任務的集合、快取最近一次的任務資料，
        並準備好非同步任務與事件中止控制。
        """
        self.active_jobs: Dict[str, int] = {}
        self.last_data: Dict[str, str] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def add_job(self, job_id: str) -> None:
        """
        加入欲監控的任務 ID（支援參考計數）。
        
        當前端透過 SSE 建立連線時呼叫。如果同一個任務有多個連線，
        只會增加參考計數，以確保單一任務只需輪詢一次。

        Args:
            job_id (str): 要加入監控的任務 ID。
        """
        self.active_jobs[job_id] = self.active_jobs.get(job_id, 0) + 1

    def remove_job(self, job_id: str) -> None:
        """
        移除不再監控的任務 ID（支援參考計數）。
        
        當前端 SSE 連線斷開時呼叫。會減少該任務的參考計數，
        當計數歸零時，正式停止對該任務的資料庫輪詢並清理快取。

        Args:
            job_id (str): 要移除監控的任務 ID。
        """
        if job_id in self.active_jobs:
            self.active_jobs[job_id] -= 1
            if self.active_jobs[job_id] <= 0:
                del self.active_jobs[job_id]
                self.last_data.pop(job_id, None)

    async def start(self) -> None:
        """
        啟動背景輪詢任務。
        
        通常在 FastAPI 應用程式的 lifespan 啟動時被呼叫。
        會建立一個非同步背景工作執行 `_poll_loop`。
        """
        self._stop_event.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop())
            logger.info("JobProgressPoller background task started.")

    async def stop(self) -> None:
        """
        停止背景輪詢任務。
        
        通常在 FastAPI 應用程式的 lifespan 關閉時被呼叫。
        會設定中止事件並優雅地等待背景工作結束。
        """
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("JobProgressPoller background task stopped.")

    async def _poll_loop(self) -> None:
        """
        輪詢迴圈。每 2 秒向資料庫查詢一次所有活躍任務的最新進度，
        並利用事件機制廣播。
        """
        manager = get_job_manager()
        while not self._stop_event.is_set():
            if not self.active_jobs:
                await asyncio.sleep(2)
                continue

            # 複製一份 active_jobs，避免在迭代過程中因為 add_job / remove_job 而改變
            current_jobs = list(self.active_jobs.keys())
            for job_id in current_jobs:
                try:
                    # 使用 bypass_auth=True 繞過內部權限檢查，安全依賴前端的 initial 連線檢查
                    job_detail = await run_in_threadpool(
                        job_management.get_job_detail,
                        manager,
                        job_id,
                        "__SYSTEM_POLLER__",
                        bypass_auth=True,
                    )
                    current_str = json.dumps(job_detail)

                    # 狀態有改變才進行廣播
                    if current_str != self.last_data.get(job_id):
                        self.last_data[job_id] = current_str
                        publish(f"job_progress_updated_{job_id}", detail_str=current_str)

                    # 若任務已經結束且不在運行中，自動移除監控
                    # （通常前端連線斷開時也會呼叫 remove_job，此為防呆機制）
                    status = job_detail.get("status")
                    if status in ["completed", "error", "paused", "pending"] and not job_detail.get("is_running"):
                        pass  # 等待前端連線中斷自動呼叫 remove_job，防呆強制移除可能會影響其他剛連線的客戶端

                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.debug("Poller polling job %s failed: %s", job_id, e)

            await asyncio.sleep(2)


# 全域單一實例
job_progress_poller = JobProgressPoller()
