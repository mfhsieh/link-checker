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

#: mcp: 負責處理 MCP 協議的 FastMCP 伺服器實例。
mcp: FastMCP = FastMCP("LinkCheckerProductionMCP")


@mcp.tool()
def get_jobs_status(job_id: str | None = None) -> str:  # pylint: disable=too-many-locals
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
    # pylint: disable=import-outside-toplevel
    from backend.auth.db import get_auth_session_local
    from backend.auth.models import User
    from backend.deps import get_job_manager
    from crawler.models import CrawlQueue, Job
    # pylint: enable=import-outside-toplevel

    auth_session_factory = get_auth_session_local()
    manager = get_job_manager()

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
    # pylint: disable=import-outside-toplevel
    from backend.deps import get_job_manager
    from crawler.models import Job
    # pylint: enable=import-outside-toplevel

    manager = get_job_manager()
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
def get_disk_usage() -> str:
    """
    取得資料庫 (Crawler DB) 與檔案系統 (root) 的空間耗用量資訊。

    幫助開發者監控 Production 環境的硬碟剩餘空間與資料庫大小。

    Returns:
        str: 包含硬碟空間與資料庫大小的 JSON 格式字串。
    """
    # pylint: disable=import-outside-toplevel
    import shutil

    from sqlalchemy import text

    from backend.deps import get_job_manager
    # pylint: enable=import-outside-toplevel

    manager = get_job_manager()

    # 1. 取得根目錄檔案系統空間
    total, used, free = shutil.disk_usage("/")

    # 2. 取得資料庫空間
    db_size_bytes = 0
    db_size_pretty = "Unknown"

    with manager.session_factory() as db:
        is_postgres = manager.engine.dialect.name == "postgresql"
        if is_postgres:
            result = db.execute(text("SELECT pg_database_size(current_database())")).scalar()
            if result is not None:
                db_size_bytes = result
        else:
            # 針對 SQLite 取得檔案大小 (page_size * page_count)
            page_size = db.execute(text("PRAGMA page_size")).scalar() or 4096
            page_count = db.execute(text("PRAGMA page_count")).scalar() or 0
            db_size_bytes = page_size * page_count

    if db_size_bytes > 0:
        db_size_pretty = f"{db_size_bytes / (1024 * 1024):.2f} MB"
        if db_size_bytes > 1024 * 1024 * 1024:
            db_size_pretty = f"{db_size_bytes / (1024 * 1024 * 1024):.2f} GB"

    info = {
        "filesystem": {
            "path": "/",
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "usage_percent": round(used / total * 100, 2) if total > 0 else 0,
        },
        "crawler_db": {
            "dialect": manager.engine.dialect.name,
            "size_bytes": db_size_bytes,
            "size_formatted": db_size_pretty,
        },
    }

    return json.dumps(info, ensure_ascii=False, indent=2)


@mcp.tool()
def test_internal_url(url: str) -> str:
    """
    透過執行 scripts/test_url.py 測試內部連結，取得 HTTP 狀態碼與解析結果。
    與直接執行 CLI 的行為與程式碼完全一致。

    Args:
        url (str): 欲測試的內部連結。

    Returns:
        str: 包含 status_code, error_msg 與連結數量的 JSON 字串。若執行失敗，則回傳錯誤訊息。
    """
    # pylint: disable=import-outside-toplevel
    import subprocess
    # pylint: enable=import-outside-toplevel

    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_url.py"))
    # 使用當前執行的 python 直譯器
    python_exe = sys.executable

    try:
        result = subprocess.run([python_exe, script_path, url, "--json"], capture_output=True, text=True, check=False)
        if result.stdout.strip():
            return result.stdout.strip()
        return json.dumps({"error": f"腳本沒有輸出。 stderr: {result.stderr.strip()}"})
    except Exception as e:  # pylint: disable=broad-exception-caught
        return json.dumps({"error": f"執行測試腳本時發生異常: {e}"})


@mcp.tool()
def test_external_url(url: str) -> str:
    """
    透過執行 scripts/test_ext.py 測試外部連結，取得 HTTP 狀態碼與解析結果。
    與直接執行 CLI 的行為與程式碼完全一致。

    Args:
        url (str): 欲測試的外部連結。

    Returns:
        str: 包含 status_code, error_msg 的 JSON 字串。若執行失敗，則回傳錯誤訊息。
    """
    # pylint: disable=import-outside-toplevel
    import subprocess
    # pylint: enable=import-outside-toplevel

    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_ext.py"))
    # 使用當前執行的 python 直譯器
    python_exe = sys.executable

    try:
        result = subprocess.run([python_exe, script_path, url, "--json"], capture_output=True, text=True, check=False)
        if result.stdout.strip():
            return result.stdout.strip()
        return json.dumps({"error": f"腳本沒有輸出。 stderr: {result.stderr.strip()}"})
    except Exception as e:  # pylint: disable=broad-exception-caught
        return json.dumps({"error": f"執行測試腳本時發生異常: {e}"})


if __name__ == "__main__":
    mcp.run()
