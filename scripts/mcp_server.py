"""
獨立運行的 MCP (Model Context Protocol) 伺服器腳本。

提供遠端開發者與 AI 助理透過 stdio 直接查詢與操作 Production 環境的任務狀態。
此模組主要作為 FastMCP 的進入點，提供供外部呼叫的工具 (Tools)。

此模組提供以下主要功能（Tools）：
- get_job_config: 取得指定任務的執行配置快照 (Config Snapshot)
- get_jobs_status: 取得指定任務的最新狀態，或列出所有執行中與等待中的任務。

模組層級變數：
    mcp (FastMCP): 負責處理 MCP 協議的伺服器實例。
    manager (JobManager): 用於與資料庫及爬蟲引擎互動的任務管理員。
"""

import json
import os
import sys

from mcp.server.fastmcp import FastMCP

# 將專案路徑加入 path 以便引用 backend, crawler
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.auth.db import get_auth_session_local  # pylint: disable=wrong-import-position
from backend.auth.models import User  # pylint: disable=wrong-import-position
from backend.deps import get_job_manager  # pylint: disable=wrong-import-position
from crawler.manager import JobManager  # pylint: disable=wrong-import-position
from crawler.models import CrawlQueue, Job  # pylint: disable=wrong-import-position

#: mcp: 負責處理 MCP 協議的 FastMCP 伺服器實例。
mcp: FastMCP = FastMCP("LinkCheckerProductionMCP")
#: manager: 用於與資料庫及爬蟲引擎互動的任務管理員。
manager: JobManager = get_job_manager()


@mcp.tool()
def get_jobs_status(job_id: str | None = None) -> str:
    """
    取得指定任務的狀態，或列出所有目前狀態為 'running' 或 'pending' 的爬蟲任務。

    此工具會跨越 Crawler DB 與 Auth DB 進行查詢，整合任務資訊與使用者信箱 (Email)，
    幫助開發者或 AI 助理掌握任務的負責人與執行狀況。
    同時，也會依據 `updated_at` (最後更新時間) 排序，附上該任務在 crawl_queue 中最新的一筆爬取紀錄。

    Args:
        job_id (str | None): 若指定，則只查詢該 UUID 對應的任務；若未指定，則列出所有 running/pending 任務。

    Returns:
        str: 包含任務詳情、使用者信箱與最新爬取紀錄的 JSON 字串列表。若無符合的任務則回傳提示訊息。
    """
    auth_session_factory = get_auth_session_local()

    with manager.session_factory() as crawler_db, auth_session_factory() as auth_db:
        query = crawler_db.query(Job)
        if job_id:
            query = query.filter(Job.id == job_id)
        else:
            query = query.filter(Job.status.in_(["running", "pending"]))
            
        jobs = query.all()
        if not jobs:
            return f"找不到指定的任務: {job_id}" if job_id else "目前沒有正在執行的任務。"

        user_ids = {job.user_id for job in jobs if job.user_id}
        user_email_map: dict[str, str] = {}

        if user_ids:
            users = auth_db.query(User).filter(User.id.in_(user_ids)).all()
            for u in users:
                user_email_map[u.id] = u.email

        result = []
        for job in jobs:
            email = user_email_map.get(job.user_id, "Unknown / System") if job.user_id else "System"
            
            latest_queue = (
                crawler_db.query(CrawlQueue)
                .filter(CrawlQueue.job_id == job.id)
                .order_by(CrawlQueue.updated_at.desc())
                .first()
            )
            
            latest_crawl_data = None
            if latest_queue:
                latest_crawl_data = {
                    "url": latest_queue.url,
                    "source_url": latest_queue.source_url,
                    "depth": latest_queue.depth,
                    "status": latest_queue.status,
                    "status_code": latest_queue.status_code,
                    "error_message": latest_queue.error_message,
                    "updated_at": latest_queue.updated_at.isoformat() if latest_queue.updated_at else None,
                }

            result.append(
                {
                    "job_id": job.id,
                    "status": job.status,
                    "start_url": job.start_url,
                    "user_email": email,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "latest_crawl": latest_crawl_data,
                }
            )

        return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_job_config(job_id: str) -> str:
    """
    取得指定任務的執行配置快照 (Config Snapshot)。

    幫助開發者或 AI 助理診斷該任務啟動時所合併的各項參數，
    例如延遲秒數、重試次數、信任網域、自訂 Header 等。

    Args:
        job_id (str): 欲查詢設定的任務 UUID。

    Returns:
        str: 該任務的執行配置 (JSON 格式字串)。若找不到該任務或沒有配置快照，則回傳錯誤訊息。
    """
    with manager.session_factory() as db:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return f"找不到指定的任務: {job_id}"
        if not job.config_json:
            return f"任務 {job_id} 沒有儲存配置快照 (config_json 為空)。"

        try:
            config_dict = json.loads(job.config_json)
            return json.dumps(config_dict, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return job.config_json


if __name__ == "__main__":
    mcp.run()
