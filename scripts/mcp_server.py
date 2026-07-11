"""
獨立運行的 MCP (Model Context Protocol) 伺服器腳本。
提供遠端開發者與 AI 助理透過 stdio 直接查詢 Production 環境的任務狀態。
"""

import json
import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import func

# 設定環境變數路徑，確保可以讀取到專案模組與設定
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# pylint: disable=wrong-import-position
from backend.deps import get_job_manager
from crawler.models import CrawlQueue, Job

mcp = FastMCP("LinkCheckerProductionMCP")
manager = get_job_manager()


@mcp.tool()
def list_active_jobs() -> str:
    """
    列出所有目前狀態為 'running' 或 'pending' 的爬蟲任務。

    此工具用於查詢系統中當前正在執行或等待執行的任務清單，幫助使用者快速了解系統活躍狀態。

    Returns:
        str: 包含任務 ID (job_id)、狀態 (status)、起始網址 (start_url)
             與建立時間 (created_at) 的 JSON 字串列表。若無任務則回傳提示訊息。
    """
    with manager.session_factory() as db:
        jobs = db.query(Job).filter(Job.status.in_(["running", "pending"])).all()
        if not jobs:
            return "目前沒有正在執行的任務。"

        result = []
        for job in jobs:
            result.append(
                {
                    "job_id": job.id,
                    "status": job.status,
                    "start_url": job.start_url,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                }
            )
        return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_job_progress(job_id: str) -> str:
    """
    取得指定任務的執行進度與各種狀態的統計數量。

    透過分析資料庫中的佇列 (CrawlQueue)，彙整特定任務中各個狀態
    （例如：ok, pending, not_found, blocked 等）的連結數量，並計算整體探索進度百分比。

    Args:
        job_id (str): 欲查詢進度的爬蟲任務 UUID。

    Returns:
        str: 包含統計結果 (stats)、已完成數 (completed)、待處理數 (pending)
             與進度百分比 (progress_percentage) 的 JSON 字串。若找不到該任務則回傳錯誤訊息。
    """
    with manager.session_factory() as db:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return f"找不到指定的任務: {job_id}"

        stats = (
            # pylint: disable=not-callable
            db.query(CrawlQueue.status_category, func.count(CrawlQueue.id).label("count"))
            .filter(CrawlQueue.job_id == job_id)
            .group_by(CrawlQueue.status_category)
            .all()
        )

        summary: dict[str, Any] = {
            "job_id": job.id,
            "status": job.status,
            "start_url": job.start_url,
            "stats": {row.status_category or "unknown": row.count for row in stats},
        }

        # 額外統計
        total = sum(summary["stats"].values())
        pending = summary["stats"].get("pending", 0)
        completed = total - pending

        summary["total_discovered"] = total
        summary["completed"] = completed
        summary["pending"] = pending
        summary["progress_percentage"] = round((completed / total * 100), 2) if total > 0 else 0

        return json.dumps(summary, ensure_ascii=False, indent=2)


@mcp.tool()
def get_job_errors(job_id: str, limit: int = 10) -> str:
    """
    取得特定任務中最近發生的錯誤紀錄與失敗細節。

    過濾掉狀態為正常 ('ok') 或等待中 ('pending') 的連結，並依照更新時間由新到舊排序，
    幫助開發者或 AI 助理快速診斷爬蟲執行過程中的網路連線錯誤或 HTTP 錯誤。

    Args:
        job_id (str): 欲查詢錯誤紀錄的爬蟲任務 UUID。
        limit (int): 限制回傳的最新錯誤筆數，預設為 10 筆。

    Returns:
        str: 包含失敗網址 (url)、狀態分類 (status_category)、錯誤訊息 (error_message)
             與狀態碼 (status_code) 的 JSON 字串列表。若無錯誤紀錄則回傳提示訊息。
    """
    with manager.session_factory() as db:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return f"找不到指定的任務: {job_id}"

        errors = (
            db.query(CrawlQueue)
            .filter(CrawlQueue.job_id == job_id, CrawlQueue.status_category.notin_(["pending", "ok"]))
            .order_by(CrawlQueue.updated_at.desc())
            .limit(limit)
            .all()
        )

        if not errors:
            return f"任務 {job_id} 目前沒有錯誤紀錄。"

        result = []
        for err in errors:
            result.append(
                {
                    "url": err.url,
                    "status_category": err.status_category,
                    "error_message": err.error_message,
                    "status_code": err.status_code,
                    "updated_at": err.updated_at.isoformat() if err.updated_at else None,
                }
            )

        return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
