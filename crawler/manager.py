"""
爬蟲任務 (Job) 管理模組。

此模組提供 JobManager 類別，負責處理資料庫互動、建立爬蟲任務、
管理爬取佇列 (Queue)、處理中斷例外，以及執行主要的爬蟲迴圈。
"""

import csv
import io
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
import zipfile
import time
from typing import Any

import httpx
from sqlalchemy import create_engine, Engine, event
from sqlalchemy.orm import sessionmaker, Session

from crawler.core import CrawlerCore
from crawler.models import Base, Job, CrawlQueue, ExternalLink
from crawler.utils import (
    resolve_ip,
    get_domain,
    is_in_domain_list,
)

try:
    from backend.auth.db import get_auth_session_local
    from backend.auth.models import User
    from backend.email_sender import send_notification_email
    _BACKEND_AVAILABLE = True
except ImportError:
    _BACKEND_AVAILABLE = False


def _get_domain_delay(
    url: str, domain_delays: dict[str, float], default_delay: float
) -> float:
    """
    根據給定網址，取得對應網域的請求延遲時間。

    比對時遵循「最長匹配優先原則」。若無匹配項目，則回傳預設的延遲時間。

    Args:
        url (str): 目標網址。
        domain_delays (dict[str, float]): 網域與對應延遲時間的字典。
        default_delay (float): 預設的延遲時間 (秒)。

    Returns:
        float: 計算出的延遲時間 (秒)。
    """
    domain = get_domain(url)
    if not domain:
        return default_delay
    domain = domain.lower()

    matched_delays = []
    for d, val in domain_delays.items():
        d_lower = d.lower()
        if domain == d_lower or domain.endswith("." + d_lower):
            try:
                matched_delays.append((d_lower, float(val)))
            except (ValueError, TypeError):
                continue

    if not matched_delays:
        return default_delay

    matched_delays.sort(key=lambda x: len(x[0]), reverse=True)
    return matched_delays[0][1]


def format_crawl_queue_item(q: CrawlQueue) -> dict[str, Any]:
    """格式化 CrawlQueue 項目為字典供報表使用。"""
    return {
        "URL": q.url,
        "Source URL": q.source_url if q.source_url else "",
        "Status": q.status,
        "Depth": q.depth,
        "Retry Count": q.retry_count,
        "HTTP Status Code": q.status_code if q.status_code is not None else "",
        "Error Message": q.error_message if q.error_message else "",
        "Created At": q.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }

logger: logging.Logger = logging.getLogger(__name__)


class JobManager:
    """
    負責在資料庫中管理爬蟲任務與佇列狀態的管理器。

    Attributes:
        engine (Engine): SQLAlchemy 的資料庫引擎物件。
        SessionLocal (sessionmaker): 用來建立新 SQLAlchemy Session 的工廠 (Factory)。
    """

    def __init__(self, db_url: str = "sqlite:///db/crawler.db") -> None:
        """
        初始化 Job 管理器並建立資料庫連線。

        Args:
            db_url (str): 資料庫的連線字串。預設為 'sqlite:///db/crawler.db'。
        """
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

        self.engine: Engine = create_engine(db_url)
        if db_url.startswith("sqlite:"):

            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
                """設定 SQLite 的 PRAGMA 參數，提升效能。"""
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA cache_size=10000")
                cursor.close()

        Base.metadata.create_all(self.engine)
        # pylint: disable=invalid-name, unsubscriptable-object
        self.SessionLocal: sessionmaker[Session] = sessionmaker(bind=self.engine)

    def _send_job_status_notification(self, job_id: str, status: str) -> None:
        """
        在任務完成或發生錯誤時，向任務建立者發送 Email 通知，並附帶結果統計。

        Args:
            job_id (str): 任務 ID。
            status (str): 結束的狀態 ('completed' 或 'error')。
        """
        if not _BACKEND_AVAILABLE:
            logger.warning("[Email Notification] 因無法載入後端模組，跳過通知信發送。")
            return

        with self.SessionLocal() as session:
            job: Job | None = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                return
            
            user_id = job.user_id
            if not user_id:
                logger.info("[Email Notification] 任務為匿名任務，不發送通知信。")
                return

            # 取得使用者的 Email
            try:
                auth_session_factory = get_auth_session_local()
                with auth_session_factory() as auth_session:
                    user = auth_session.query(User).filter(User.id == user_id).first()
                    if not user or not user.email:
                        logger.warning("[Email Notification] 找不到使用者 ID %s 或其無信箱設定，跳過通知信發送。", user_id)
                        return
                    to_email = user.email
            except Exception as ex:
                logger.error("[Email Notification] 自 Auth DB 查詢使用者 %s 的信箱時發生錯誤: %s", user_id, ex)
                return

            # 統計外部連結狀態
            # dead: DNS 解析失敗（IP 為 None 或空）
            dead_count = (
                session.query(ExternalLink)
                .filter(
                    ExternalLink.job_id == job_id,
                    (ExternalLink.ip_address.is_(None)) | (ExternalLink.ip_address == ""),
                )
                .count()
            )
            # broken: HTTP 狀態碼 >= 400
            broken_count = (
                session.query(ExternalLink)
                .filter(
                    ExternalLink.job_id == job_id,
                    ExternalLink.http_status_code >= 400,
                )
                .count()
            )
            # 總外連數
            total_count = session.query(ExternalLink).filter(ExternalLink.job_id == job_id).count()

            # 組裝信件
            status_text = "已完成 (Completed)" if status == "completed" else "發生嚴重異常 (Error)"
            subject = f"【外部連結檢查系統】任務狀態通知 ({status_text}) - 任務 ID: {job_id}"

            plain_text = (
                f"您好，\n\n"
                f"您所建立的外部連結檢查任務已執行結束。\n\n"
                f"任務資訊：\n"
                f"  - 任務 ID：{job_id}\n"
                f"  - 起始網址：{job.start_url}\n"
                f"  - 任務狀態：{status_text}\n"
                f"  - 建立時間：{job.created_at}\n"
                f"  - 結束時間：{job.updated_at}\n\n"
                f"外部連結檢查統計：\n"
                f"  - 總共發現外部連結數：{total_count}\n"
                f"  - 損壞連結 (Broken Links，HTTP 狀態碼 >= 400)：{broken_count} 個\n"
                f"  - 失效連結 (Dead Links，DNS 解析失敗)：{dead_count} 個\n\n"
                f"詳細檢查結果，請登入系統後台查看。\n\n"
                f"此為系統自動發送的郵件，請勿回覆。"
            )

            html_body = f"""\
<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"></head>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#333;">
  <h2 style="color:#1a1a2e;border-bottom:2px solid #eee;padding-bottom:12px;">外部連結檢查任務通知</h2>
  <p>您好，</p>
  <p>您所建立的外部連結檢查任務已執行結束。</p>
  
  <table style="width:100%;border-collapse:collapse;margin:20px 0;background:#f9f9f9;border-radius:6px;overflow:hidden;">
    <tr style="border-bottom:1px solid #eee;">
      <td style="padding:10px;font-weight:bold;width:120px;">任務 ID</td>
      <td style="padding:10px;font-family:monospace;">{job_id}</td>
    </tr>
    <tr style="border-bottom:1px solid #eee;">
      <td style="padding:10px;font-weight:bold;">起始網址</td>
      <td style="padding:10px;"><a href="{job.start_url}" target="_blank">{job.start_url}</a></td>
    </tr>
    <tr style="border-bottom:1px solid #eee;">
      <td style="padding:10px;font-weight:bold;">任務狀態</td>
      <td style="padding:10px;color:{"#10b981" if status == "completed" else "#ef4444"};font-weight:bold;">{status_text}</td>
    </tr>
    <tr style="border-bottom:1px solid #eee;">
      <td style="padding:10px;font-weight:bold;">建立時間</td>
      <td style="padding:10px;">{job.created_at}</td>
    </tr>
    <tr>
      <td style="padding:10px;font-weight:bold;">結束時間</td>
      <td style="padding:10px;">{job.updated_at}</td>
    </tr>
  </table>

  <h3 style="color:#2563eb;margin-top:24px;">外部連結檢查統計</h3>
  <ul style="padding-left:20px;line-height:1.6;">
    <li>總共發現外部連結數：<strong>{total_count}</strong></li>
    <li>損壞連結 (Broken Links，HTTP 狀態碼 &gt;= 400)：<span style="color:#ef4444;font-weight:bold;">{broken_count}</span> 個</li>
    <li>失效連結 (Dead Links，DNS 解析失敗)：<span style="color:#ef4444;font-weight:bold;">{dead_count}</span> 個</li>
  </ul>

  <p style="margin-top:24px;">詳細檢查結果與完整匯出報表，請登入系統後台查看。</p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
  <p style="color:#999;font-size:0.75rem;">此為系統自動發送的郵件，請勿回覆。</p>
</body>
</html>"""

            try:
                # 寄出郵件
                send_notification_email(to_email, subject, plain_text, html_body)
            except Exception as ex:
                logger.error("[Email Notification] 寄送任務通知信失敗: %s", ex)

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def create_job(
        self,
        start_url: str,
        target_domains: list[str],
        internal_domains: list[str],
        crawler_config: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> str:
        """
        建立一個全新的爬蟲任務，並將起始網址加入到佇列中。

        Args:
            start_url (str): 準備進行爬取的起始網址。
            target_domains (list[str]): 允許爬蟲深入遍歷的網域陣列。
            internal_domains (list[str]): 被視為內部網站的網域陣列。
            crawler_config (dict[str, Any] | None): (選填) 要寫入資料庫鎖定的爬蟲設定。
            user_id (str | None): (選填) 該任務的擁有者 ID。

        Returns:
            str: 新建立任務的 ID。
        """
        config_str: str | None = (
            json.dumps(crawler_config) if crawler_config is not None else None
        )

        with self.SessionLocal() as session:
            job: Job = Job(
                user_id=user_id,
                start_url=start_url,
                target_domains=",".join(target_domains),
                internal_domains=",".join(internal_domains),
                status="pending",
                config_json=config_str,
            )
            session.add(job)
            session.commit()

            # 將起始網址加入佇列
            queue_item: CrawlQueue = CrawlQueue(
                job_id=job.id, url=start_url, source_url=None, status="pending", depth=0
            )
            session.add(queue_item)
            session.commit()

            return job.id

    def get_job(self, job_id: str) -> Job | None:
        """
        透過 ID 查詢並取得特定的任務物件。

        Args:
            job_id (str): 欲查詢的任務 ID。

        Returns:
            Job | None: 若找到對應的任務物件則回傳，否則回傳 None。
        """
        with self.SessionLocal() as session:
            return session.query(Job).filter(Job.id == job_id).first()

    # pylint: disable=too-many-locals, too-many-branches, too-many-statements, too-many-nested-blocks
    def run_job(
        self,
        job_id: str,
        crawler_config: dict[str, Any] | None = None,
        force: bool = False,
    ) -> None:
        """
        執行指定的爬蟲任務，直到佇列清空或遭到使用者中斷為止。

        Args:
            job_id (str): 欲執行的任務 ID。
            crawler_config (dict[str, Any] | None): 爬蟲相關的設定參數。
            force (bool): 是否強制接管卡在 running 狀態的任務。
        """
        with self.SessionLocal() as session:
            job: Job | None = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return

            if job.status in ["completed", "error"]:
                logger.warning(
                    "任務 %s 的狀態已經是 %s，無法再次執行。", job_id, job.status
                )
                return

            if job.status == "running" and not force:
                logger.error(
                    "任務 %s 目前正在執行中。如果確定前次程序已經意外終止，"
                    "請加上 -f 或 --force 參數強制接管任務。",
                    job_id,
                )
                return

            job.status = "running"
            session.commit()

            target_domains_list: list[str] = (
                job.target_domains.split(",") if job.target_domains else []
            )
            internal_domains_list: list[str] = (
                job.internal_domains.split(",") if job.internal_domains else []
            )

            if crawler_config is None:
                # 代表從 Resume 恢復執行，需從資料庫讀取當時的設定檔
                if job.config_json:
                    try:
                        crawler_config = json.loads(job.config_json)
                        logger.info(
                            "已從資料庫成功載入任務 %s 的專屬設定參數。", job_id
                        )
                    except json.JSONDecodeError:
                        logger.error(
                            "任務 %s 的設定檔解析失敗，將退回使用預設設定。", job_id
                        )
                        crawler_config = {}
                else:
                    crawler_config = {}

            # 合併全域設定與個別任務設定
            timeout = crawler_config.get("timeout", 30)
            retries = crawler_config.get("retries", 3)
            delay = crawler_config.get("delay", 1.0)
            domain_delays = crawler_config.get("domain_delays", {}) or {}
            ignore_extensions = crawler_config.get("ignore_extensions", None)
            mime_type_filter = crawler_config.get("mime_type_filter", None)
            ignore_regexes = crawler_config.get("ignore_regexes", None)
            user_agent = crawler_config.get("user_agent", None)
            ssl_exempt_domains = crawler_config.get("ssl_exempt_domains", []) or []
            proxy_url = crawler_config.get("proxy_url", None)
            max_depth = crawler_config.get("max_depth", None)
            max_pages = crawler_config.get("max_pages", None)

            # 建立爬蟲核心實例
            crawler = CrawlerCore(
                timeout=timeout,
                ignore_extensions=ignore_extensions,
                mime_type_filter=mime_type_filter,
                ignore_regexes=ignore_regexes,
                user_agent=user_agent,
                ssl_exempt_domains=ssl_exempt_domains,
                proxy_url=proxy_url,
            )

            # 統計該任務已發送實質請求的頁面數量
            crawled_count = (
                session.query(CrawlQueue)
                .filter(
                    CrawlQueue.job_id == job_id,
                    (CrawlQueue.status.in_(["completed", "failed"]))
                    | (
                        (CrawlQueue.status == "skip")
                        & (CrawlQueue.status_code.isnot(None))
                    ),
                )
                .count()
            )

            # 預熱外連快取：載入此任務已探測過的外連結果以防重複探測
            checked_links_cache: dict[
                str, tuple[str | None, int | None, str | None]
            ] = {}
            for ext in (
                session.query(ExternalLink).filter(ExternalLink.job_id == job_id).all()
            ):
                if ext.http_status_code is not None or ext.error_message is not None:
                    checked_links_cache[ext.target_url] = (
                        ext.ip_address,
                        ext.http_status_code,
                        ext.error_message,
                    )

            try:
                while True:
                    # 協同暫停檢查：確認任務狀態是否在外部被更改
                    session.expire(job)
                    current_job: Job | None = (
                        session.query(Job).filter(Job.id == job_id).first()
                    )
                    if not current_job or current_job.status != "running":
                        logger.info(
                            "偵測到任務狀態變更為 %s，中斷爬取。",
                            current_job.status if current_job else "None",
                        )
                        break

                    if max_pages is not None and crawled_count >= max_pages:
                        logger.info(
                            "任務 %s 已達到最大抓取頁數限制 (%s)。優雅結束任務。",
                            job_id,
                            max_pages,
                        )
                        job.status = "completed"
                        session.commit()
                        self._send_job_status_notification(job_id, "completed")
                        break

                    # 從佇列中取得下一個等待處理的網址，依據 ID 排序以保障 FIFO 的 BFS 順序
                    queue_item: CrawlQueue | None = (
                        session.query(CrawlQueue)
                        .filter(
                            CrawlQueue.job_id == job_id, CrawlQueue.status == "pending"
                        )
                        .order_by(CrawlQueue.id)
                        .first()
                    )

                    if not queue_item:
                        logger.info("任務 %s 已無等待中的網址。任務完成。", job_id)
                        job.status = "completed"
                        session.commit()
                        self._send_job_status_notification(job_id, "completed")
                        break

                    current_url: str = queue_item.url
                    logger.info("正在爬取: %s", current_url)

                    should_delay = True
                    try:
                        internal_links: list[str]
                        external_target_links: list[str]
                        status_code: int | None
                        status: str
                        request_sent: bool

                        # 若設定了最大爬取深度，且目前項目的深度已超過該限制，則略過不再往下爬行。
                        # 註：當 queue_item.depth == max_depth 時，此條件不成立，網頁仍會被爬取並探測外連；
                        # 但其內連深度為 depth + 1，會因後續 next_depth <= max_depth 判斷而被拒絕加入佇列，
                        # 從而完美實現「達到最大深度時仍解析外連但不加入內部佇列」的要求。
                        if max_depth is not None and queue_item.depth > max_depth:
                            # 即使略過爬行，仍須在佇列標記為已略過
                            queue_item.status = "skip"
                            session.commit()
                            continue

                        (
                            internal_links,
                            external_target_links,
                            status_code,
                            status,
                            request_sent,
                        ) = crawler.process_url(
                            current_url, target_domains_list, internal_domains_list
                        )

                        # 將狀態與狀態碼寫回佇列項目
                        queue_item.status_code = status_code
                        queue_item.status = status
                        session.commit()

                        # 處理內部連結：如果尚未存在佇列中且未超過最大探索深度，則新增為 pending，深度遞增
                        next_depth = queue_item.depth + 1
                        if max_depth is None or next_depth <= max_depth:
                            for link in internal_links:
                                exists = (
                                    session.query(CrawlQueue)
                                    .filter(
                                        CrawlQueue.job_id == job_id,
                                        CrawlQueue.url == link,
                                    )
                                    .first()
                                )
                                if not exists:
                                    new_item = CrawlQueue(
                                        job_id=job_id,
                                        url=link,
                                        source_url=current_url,
                                        status="pending",
                                        depth=next_depth,
                                    )
                                    session.add(new_item)
                        session.commit()

                        # 處理外部連結：如果是目標外部連結，則進行探測並記錄。
                        # 先對本次頁面發現的外連進行去重，避免同一頁內重複處理相同的外部連結。
                        unique_external_links = list(set(external_target_links))
                        links_needing_http_check = []
                        for link in unique_external_links:
                            # 檢查資料庫中是否已存在相同的 (job_id, source_url, target_url) 紀錄
                            exists = (
                                session.query(ExternalLink)
                                .filter(
                                    ExternalLink.job_id == job_id,
                                    ExternalLink.source_url == current_url,
                                    ExternalLink.target_url == link,
                                )
                                .first()
                            )
                            if exists:
                                continue

                            # 如果之前已經探測過且有快取，則直接複用快取結果寫入資料庫
                            if link in checked_links_cache:
                                cached_ip, cached_code, cached_err = (
                                    checked_links_cache[link]
                                )
                                is_sec = link.startswith("https://")
                                new_ext = ExternalLink(
                                    job_id=job_id,
                                    source_url=current_url,
                                    target_url=link,
                                    ip_address=cached_ip,
                                    is_secure=is_sec,
                                    http_status_code=cached_code,
                                    error_message=cached_err,
                                )
                                session.add(new_ext)
                            else:
                                links_needing_http_check.append(link)

                        if links_needing_http_check:
                            # 並發處理實際需要進行探測的外部連結，最快提升檢測效能
                            def check_single_link(
                                l: str,
                            ) -> tuple[str, str | None, int | None, str | None]:
                                """獨立進行單一外部連結的存活與 IP 解析檢查。"""
                                tgt_dom = get_domain(l)
                                ip_res = resolve_ip(tgt_dom) if tgt_dom else None
                                code_res, err_res = crawler.check_external_link(l)
                                return l, ip_res, code_res, err_res

                            with ThreadPoolExecutor(max_workers=5) as executor:
                                results = list(
                                    executor.map(
                                        check_single_link, links_needing_http_check
                                    )
                                )

                            for link, ip, status_code, err_msg in results:
                                # 寫入快取供後續網頁共享
                                checked_links_cache[link] = (ip, status_code, err_msg)
                                # 再次防禦性檢查以防並行環境下重複寫入
                                exists = (
                                    session.query(ExternalLink)
                                    .filter(
                                        ExternalLink.job_id == job_id,
                                        ExternalLink.source_url == current_url,
                                        ExternalLink.target_url == link,
                                    )
                                    .first()
                                )
                                if not exists:
                                    is_sec = link.startswith("https://")
                                    new_ext = ExternalLink(
                                        job_id=job_id,
                                        source_url=current_url,
                                        target_url=link,
                                        ip_address=ip,
                                        is_secure=is_sec,
                                        http_status_code=status_code,
                                        error_message=err_msg,
                                    )
                                    session.add(new_ext)

                        queue_item.status = status
                        session.commit()

                        # 根據是否有發出請求決定是否延遲
                        should_delay = request_sent
                        if request_sent:
                            crawled_count += 1

                    except Exception as e:  # pylint: disable=broad-exception-caught
                        # 嘗試擷取 HTTP 狀態碼
                        status_code = None
                        is_permanent_error = False

                        if isinstance(e, httpx.HTTPStatusError):
                            status_code = e.response.status_code
                            queue_item.status_code = status_code
                            logger.error(
                                "抓取 %s 時發生 HTTP 狀態碼錯誤 %s",
                                current_url,
                                status_code,
                            )

                            # 404 與 403 視為永久性錯誤
                            if status_code in (404, 403):
                                is_permanent_error = True
                        elif isinstance(e, httpx.RequestError):
                            queue_item.status_code = None
                            logger.error(
                                "抓取 %s 時發生連線請求錯誤: %s", current_url, e
                            )
                        else:
                            queue_item.status_code = None
                            logger.error("抓取 %s 時發生未預期例外: %s", current_url, e)

                        if is_permanent_error:
                            logger.error(
                                "網址 %s 遭遇永久性錯誤 (%s)，直接標記為 failed，不進行重試。",
                                current_url,
                                status_code,
                            )
                            queue_item.status = "failed"
                            queue_item.error_message = f"永久性錯誤: {e}"
                            session.commit()
                            crawled_count += 1
                        else:
                            if queue_item.retry_count < retries:
                                queue_item.retry_count += 1
                                current_domain_delay = _get_domain_delay(
                                    current_url, domain_delays, delay
                                )
                                backoff_delay = current_domain_delay * (
                                    2 ** (queue_item.retry_count - 1)
                                )
                                logger.warning(
                                    "處理網址 %s 發生暫時性錯誤，將進行重試 (第 %s/%s 次)。"
                                    "啟用指數退避延遲 %s 秒...",
                                    current_url,
                                    queue_item.retry_count,
                                    retries,
                                    f"{backoff_delay:.1f}",
                                )
                                session.commit()
                                time.sleep(backoff_delay)
                            else:
                                logger.error(
                                    "處理網址 %s 時發生錯誤且已達重試上限", current_url
                                )
                                queue_item.status = "failed"
                                queue_item.error_message = str(e)
                                session.commit()
                                crawled_count += 1

                    # 避免頻繁請求，加入短暫的延遲
                    if should_delay:
                        current_domain_delay = _get_domain_delay(
                            current_url, domain_delays, delay
                        )
                        time.sleep(current_domain_delay)

            except KeyboardInterrupt:
                logger.info("任務 %s 已由使用者強制中斷。暫停任務中...", job_id)
                job_check: Job | None = (
                    session.query(Job).filter(Job.id == job_id).first()
                )
                if job_check and job_check.status == "running":
                    job_check.status = "paused"
                    session.commit()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("任務 %s 發生未預期例外: %s", job_id, e)
                job_err: Job | None = (
                    session.query(Job).filter(Job.id == job_id).first()
                )
                if job_err:
                    job_err.status = "error"
                    session.commit()
                    self._send_job_status_notification(job_id, "error")
            finally:
                crawler.close()

    def get_all_jobs(self, user_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        """
        取得所有任務的列表與基本資訊。可透過 user_id 進行過濾。

        Args:
            user_id (str | None): (選填) 若提供，則僅回傳該擁有者的任務。
            status (str | None): (選填) 依據任務狀態進行過濾。

        Returns:
            list[dict[str, Any]]: 包含任務基本資訊的字典陣列。
        """
        with self.SessionLocal() as session:
            query = session.query(Job)
            if user_id:
                query = query.filter(Job.user_id == user_id)
            if status:
                query = query.filter(Job.status == status)
            jobs = query.order_by(Job.created_at.desc()).all()
            return [
                {
                    "id": job.id,
                    "user_id": job.user_id,
                    "start_url": job.start_url,
                    "status": job.status,
                    "created_at": job.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for job in jobs
            ]

    def get_job_report(self, job_id: str) -> dict[str, Any] | None:
        """
        取得指定任務的詳細統計報告。

        Args:
            job_id (str): 欲查詢報告的任務 ID。

        Returns:
            dict[str, Any] | None: 任務的詳細統計資料。若任務不存在則回傳 None。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                return None

            total_queue = (
                session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).count()
            )
            completed = (
                session.query(CrawlQueue)
                .filter(CrawlQueue.job_id == job_id, CrawlQueue.status == "completed")
                .count()
            )
            pending = (
                session.query(CrawlQueue)
                .filter(CrawlQueue.job_id == job_id, CrawlQueue.status == "pending")
                .count()
            )
            failed = (
                session.query(CrawlQueue)
                .filter(CrawlQueue.job_id == job_id, CrawlQueue.status == "failed")
                .count()
            )
            skipped = (
                session.query(CrawlQueue)
                .filter(CrawlQueue.job_id == job_id, CrawlQueue.status == "skip")
                .count()
            )

            total_external = (
                session.query(ExternalLink)
                .filter(ExternalLink.job_id == job_id)
                .count()
            )

            return {
                "id": job.id,
                "start_url": job.start_url,
                "status": job.status,
                "created_at": job.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": job.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                "queue": {
                    "total": total_queue,
                    "completed": completed,
                    "skipped": skipped,
                    "pending": pending,
                    "failed": failed,
                },
                "external_links": total_external,
            }

    # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    def export_job_results(
        self,
        job_id: str,
        output_path: str,
        status_filter: str | None = None,
        export_group: bool = False,
        group_by: str = "none",
    ) -> bool:
        """
        將指定任務收集到的外部連結匯出為 CSV 或 JSON 格式。

        Args:
            job_id (str): 欲匯出結果的任務 ID。
            output_path (str): 匯出檔案的目的地路徑。
            status_filter (str | None): (選填) 'dead', 'broken' 或 'insecure' 的過濾條件。
            export_group (bool): (已棄用) 向下相容，請改用 group_by="target"。
            group_by (str): 聚合模式 ("none", "target", "source", "domain")。

        Returns:
            bool: 匯出成功則回傳 True，發生錯誤或任務不存在回傳 False。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False

            query = session.query(ExternalLink).filter(ExternalLink.job_id == job_id)

            # dead: DNS 解析失敗 (IP 位址為空)
            if status_filter == "dead":
                query = query.filter(
                    (ExternalLink.ip_address.is_(None))
                    | (ExternalLink.ip_address == "")
                )
            # broken: 有 HTTP 回應但狀態碼 >= 400（不含 NULL，NULL 屬於連線錯誤/尚未探測）
            elif status_filter == "broken":
                query = query.filter(ExternalLink.http_status_code >= 400)
            elif status_filter == "insecure":
                query = query.filter(ExternalLink.is_secure.is_(False))

            links = query.order_by(ExternalLink.created_at).all()

            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            is_json = output_path.lower().endswith(".json")

            try:
                if export_group and group_by == "none":
                    group_by = "target"

                if group_by == "target":
                    # 依外部目標去重聚合
                    agg_data = defaultdict(
                        lambda: {
                            "ip": "",
                            "is_secure": True,
                            "status_code": None,
                            "error": "",
                            "count": 0,
                            "sources": set(),
                        }
                    )
                    for link in links:
                        tgt = link.target_url
                        d = agg_data[tgt]
                        d["count"] += 1
                        d["sources"].add(link.source_url)
                        d["is_secure"] = link.is_secure
                        if link.ip_address and not d["ip"]:
                            d["ip"] = link.ip_address
                        if (
                            link.http_status_code is not None
                            and d["status_code"] is None
                        ):
                            d["status_code"] = link.http_status_code
                        if link.error_message and not d["error"]:
                            d["error"] = link.error_message

                    if is_json:
                        json_data = []
                        for tgt, d in agg_data.items():
                            json_data.append(
                                {
                                    "target_url": tgt,
                                    "ip_address": d["ip"] if d["ip"] else None,
                                    "is_secure": d["is_secure"],
                                    "http_status_code": d["status_code"],
                                    "error_message": d["error"] if d["error"] else None,
                                    "occurrence_count": d["count"],
                                    "source_urls": sorted(list(d["sources"])),
                                }
                            )
                        with open(output_path, "w", encoding="utf-8") as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=2)
                    else:
                        with open(output_path, "w", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            writer.writerow(
                                [
                                    "Target URL",
                                    "IP Address",
                                    "Is Secure",
                                    "HTTP Status Code",
                                    "Error Message",
                                    "Occurrence Count",
                                    "Source URLs",
                                ]
                            )
                            for tgt, d in agg_data.items():
                                writer.writerow(
                                    [
                                        tgt,
                                        d["ip"],
                                        d["is_secure"],
                                        (
                                            d["status_code"]
                                            if d["status_code"] is not None
                                            else ""
                                        ),
                                        d["error"],
                                        d["count"],
                                        ", ".join(sorted(list(d["sources"]))),
                                    ]
                                )
                elif group_by == "source":
                    # 依自家網頁 (修補視角) 聚合
                    agg_source = defaultdict(lambda: {"count": 0, "targets": []})
                    for link in links:
                        d = agg_source[link.source_url]
                        d["count"] += 1
                        status_str = str(link.http_status_code) if link.http_status_code is not None else ("DNS Failed" if not link.ip_address else "Error")
                        d["targets"].append({
                            "url": link.target_url,
                            "status": status_str,
                        })
                    
                    if is_json:
                        json_data = []
                        for src, d in agg_source.items():
                            json_data.append({
                                "source_url": src,
                                "occurrence_count": d["count"],
                                "targets": d["targets"]
                            })
                        with open(output_path, "w", encoding="utf-8") as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=2)
                    else:
                        with open(output_path, "w", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            writer.writerow(["Source URL", "Occurrence Count", "Target URLs"])
                            for src, d in agg_source.items():
                                targets_str = "\n".join([f"[{t['status']}] {t['url']}" for t in d["targets"]])
                                writer.writerow([
                                    src,
                                    d["count"],
                                    targets_str
                                ])
                elif group_by == "domain":
                    # 依外部網域聚合 (資安盤點)
                    agg_domain: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "urls": set()})
                    for link in links:
                        dom = get_domain(link.target_url) or "unknown"
                        d = agg_domain[dom]
                        d["count"] += 1
                        d["urls"].add(link.target_url)
                    
                    # 依出現次數排序
                    sorted_domains = sorted(agg_domain.items(), key=lambda x: x[1]["count"], reverse=True)
                    
                    if is_json:
                        json_data = []
                        for dom, d in sorted_domains:
                            json_data.append({
                                "domain": dom,
                                "occurrence_count": d["count"],
                                "unique_urls_count": len(d["urls"]),
                                "unique_urls": sorted(list(d["urls"]))
                            })
                        with open(output_path, "w", encoding="utf-8") as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=2)
                    else:
                        with open(output_path, "w", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            writer.writerow(["Domain", "Occurrence Count", "Unique URLs Count", "Unique URLs"])
                            for dom, d in sorted_domains:
                                urls_str = "\n".join(sorted(list(d["urls"])))
                                writer.writerow([
                                    dom,
                                    d["count"],
                                    len(d["urls"]),
                                    urls_str
                                ])
                elif group_by == "none":
                    # 一般平鋪導出 (不聚合)
                    if is_json:
                        json_data = []
                        for link in links:
                            json_data.append(
                                {
                                    "source_url": link.source_url,
                                    "target_url": link.target_url,
                                    "ip_address": (
                                        link.ip_address if link.ip_address else None
                                    ),
                                    "is_secure": link.is_secure,
                                    "http_status_code": link.http_status_code,
                                    "error_message": (
                                        link.error_message
                                        if link.error_message
                                        else None
                                    ),
                                    "created_at": link.created_at.strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                }
                            )
                        with open(output_path, "w", encoding="utf-8") as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=2)
                    else:
                        with open(output_path, "w", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            writer.writerow(
                                [
                                    "Source URL",
                                    "Target URL",
                                    "IP Address",
                                    "Is Secure",
                                    "HTTP Status Code",
                                    "Error Message",
                                    "Found At",
                                ]
                            )
                            for link in links:
                                writer.writerow(
                                    [
                                        link.source_url,
                                        link.target_url,
                                        link.ip_address if link.ip_address else "",
                                        link.is_secure,
                                        (
                                            link.http_status_code
                                            if link.http_status_code is not None
                                            else ""
                                        ),
                                        (
                                            link.error_message
                                            if link.error_message
                                            else ""
                                        ),
                                        link.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                                    ]
                                )
                return True
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("匯出檔案時發生錯誤: %s", e)
                return False

    def export_full_report(self, job_id: str, output_path: str) -> bool:
        """
        匯出完整報表 (ZIP 壓縮檔)，內含爬取紀錄與外連清單。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False
            
            q_items = session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).order_by(CrawlQueue.id).all()
            e_items = session.query(ExternalLink).filter(ExternalLink.job_id == job_id).order_by(ExternalLink.created_at).all()
            
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            try:
                with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    if q_items:
                        cq_io = io.StringIO()
                        cq_writer = csv.writer(cq_io)
                        cq_writer.writerow(["URL", "Source URL", "Status", "Depth", "Retry Count", "HTTP Status Code", "Error Message", "Created At"])
                        for q in q_items:
                            d = format_crawl_queue_item(q)
                            cq_writer.writerow([d["URL"], d["Source URL"], d["Status"], d["Depth"], d["Retry Count"], d["HTTP Status Code"], d["Error Message"], d["Created At"]])
                        zf.writestr(f"job_{job_id}_crawl_records.csv", cq_io.getvalue().encode("utf-8-sig"))
                        
                    if e_items:
                        el_io = io.StringIO()
                        el_writer = csv.writer(el_io)
                        el_writer.writerow(["Source URL", "Target URL", "IP Address", "Is Secure", "HTTP Status Code", "Error Message", "Found At"])
                        for link in e_items:
                            el_writer.writerow([
                                link.source_url, link.target_url, link.ip_address if link.ip_address else "",
                                link.is_secure, link.http_status_code if link.http_status_code is not None else "",
                                link.error_message if link.error_message else "", link.created_at.strftime("%Y-%m-%d %H:%M:%S")
                            ])
                        zf.writestr(f"job_{job_id}_external_links.csv", el_io.getvalue().encode("utf-8-sig"))
                return True
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("匯出完整報表時發生錯誤: %s", e)
                return False

    def pause_job(self, job_id: str) -> bool:
        """
        將指定任務狀態更新為 paused（僅在任務當前為 running 時允許）。

        Args:
            job_id (str): 欲暫停的任務 ID。

        Returns:
            bool: 成功暫停回傳 True，否則回傳 False。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False
            if job.status == "running":
                job.status = "paused"
                session.commit()
                return True
            logger.warning(
                "任務 %s 當前狀態為 %s，非 running，無法暫停。", job_id, job.status
            )
            return False

    def delete_job(self, job_id: str) -> bool:
        """
        刪除指定任務，並利用級聯刪除 (Cascade Delete) 機制清理其所有佇列與外連結果。

        Args:
            job_id (str): 欲刪除的任務 ID。

        Returns:
            bool: 成功刪除回傳 True，若任務不存在則回傳 False。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False
            session.delete(job)
            session.commit()
            return True

    def reset_job(self, job_id: str) -> bool:
        """
        重設指定任務：將任務狀態設回 pending，清除已發生的外連記錄，重置佇列。

        Args:
            job_id (str): 欲重設的任務 ID。

        Returns:
            bool: 成功重設回傳 True，若任務不存在則回傳 False。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False

            # 執行中的任務不允許直接重置，避免子程序仍在運行時造成狀態不一致
            if job.status == "running":
                logger.error(
                    "任務 %s 目前正在執行中，無法直接重置。請先暫停任務再進行重置。", job_id
                )
                return False

            job.status = "pending"

            # 清除外連記錄
            session.query(ExternalLink).filter(ExternalLink.job_id == job_id).delete()

            # 清除佇列中除起始網址外的所有記錄
            session.query(CrawlQueue).filter(
                CrawlQueue.job_id == job_id, CrawlQueue.url != job.start_url
            ).delete()

            # 重設起始網址的佇列狀態
            start_queue = (
                session.query(CrawlQueue)
                .filter(CrawlQueue.job_id == job_id, CrawlQueue.url == job.start_url)
                .first()
            )
            if start_queue:
                start_queue.status = "pending"
                start_queue.retry_count = 0
                start_queue.status_code = None
                start_queue.error_message = None
            else:
                new_start = CrawlQueue(
                    job_id=job_id, url=job.start_url, source_url=None, status="pending"
                )
                session.add(new_start)

            session.commit()
            return True
