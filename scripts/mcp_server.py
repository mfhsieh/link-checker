"""
獨立運行的 MCP (Model Context Protocol) 伺服器腳本。
提供遠端開發者與 AI 助理透過 stdio 直接查詢 Production 環境的任務狀態。
"""

import json
import os
import sys

from mcp.server.fastmcp import FastMCP
from sqlalchemy import func

# 將專案路徑加入 path 以便引用 backend, crawler
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.deps import get_job_manager  # pylint: disable=wrong-import-position
from crawler.models import CrawlQueue, Job  # pylint: disable=wrong-import-position

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
    取得指定任務的內部網頁探索進度與各狀態統計。

    專注於查詢資料庫中的內部網頁佇列 (CrawlQueue)，彙整各個狀態
    （如：ok, pending, not_found 等）的數量，並計算整體進度百分比。
    注意：此工具「不包含」外部連結的統計，適合在任務「執行中」高頻輪詢以即時取得探索進度。

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

        stats_dict: dict[str, int] = {row[0] or "unknown": row[1] for row in stats}

        summary: dict[str, object] = {
            "job_id": job.id,
            "status": job.status,
            "start_url": job.start_url,
            "stats": stats_dict,
        }

        # 額外統計
        total = sum(stats_dict.values())
        pending = stats_dict.get("pending", 0)
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


@mcp.tool()
def get_job_report(job_id: str) -> str:
    """
    取得指定任務的全方位綜合統計報告 (Job Report)。

    相較於 get_job_progress，此工具不僅提供內部網頁佇列的狀態，
    還會跨表聚合「外部連結 (ExternalLink)」的各項存活狀態總數與網域統計。
    適合在「任務完成後」呼叫，作為 AI 撰寫最終健檢總結與分析的依據。

    Args:
        job_id (str): 欲查詢報告的任務 UUID。

    Returns:
        str: 包含該任務詳細統計報表的 JSON 字串。若找不到該任務則回傳錯誤訊息。
    """
    report = manager.get_job_report(job_id)
    if not report:
        return f"找不到指定的任務或產生報告失敗: {job_id}"
    return json.dumps(report, ensure_ascii=False, indent=2)


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


@mcp.tool()
def pause_job(job_id: str) -> str:
    """
    對執行中的任務發送暫停指令 (Pause Signal)。

    透過核心管理員將任務狀態標記為 'paused'，爬蟲核心會在完成當前處理的網址後，
    進行安全的溫和暫停 (Cooperative Cancellation)。

    Args:
        job_id (str): 欲暫停的任務 UUID。

    Returns:
        str: 暫停指令是否成功發送的結果訊息。
    """
    success = manager.pause_job(job_id)
    if success:
        return f"任務 {job_id} 的暫停信號已成功發出。爬蟲核心將在目前網址處理完畢後停止。"

    return f"暫停任務 {job_id} 失敗 (任務可能不存在，或狀態不允許暫停)。"


if __name__ == "__main__":
    mcp.run()
