"""
爬蟲任務 (Job) 管理模組。

此模組提供 JobManager 類別，負責處理資料庫互動、建立爬蟲任務、
管理爬取佇列 (Queue)、處理中斷例外，以及執行主要的爬蟲迴圈。
"""

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
import time

import httpx
from sqlalchemy import create_engine, Engine, event
from sqlalchemy.orm import sessionmaker, Session

from crawler.core import CrawlerCore
from crawler.models import Base, Job, CrawlQueue, ExternalLink
from crawler.utils import (
    resolve_ip,
    get_domain,
)
from crawler.notifier import send_job_status_notification


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

        self.engine: Engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False}
            if db_url.startswith("sqlite")
            else {},
        )
        if db_url.startswith("sqlite:"):

            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(
                dbapi_connection: object, _connection_record: object
            ) -> None:
                """
                設定 SQLite 的 PRAGMA 參數，提升效能。

                Args:
                    dbapi_connection (object): SQLite 連線物件。
                    _connection_record (object): SQLAlchemy 連線紀錄。
                """
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA cache_size=10000")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        Base.metadata.create_all(self.engine)
        # pylint: disable=invalid-name, unsubscriptable-object
        self.SessionLocal: sessionmaker[Session] = sessionmaker(bind=self.engine)

    # pylint: disable=too-many-arguments
    def create_job(
        self,
        start_url: str,
        target_domains: list[str],
        internal_domains: list[str],
        crawler_config: dict[str, object] | None = None,
        user_id: str | None = None,
    ) -> str:
        """
        建立一個全新的爬蟲任務，並將起始網址加入到佇列中。

        Args:
            start_url (str): 準備進行爬取的起始網址。
            target_domains (list[str]): 允許爬蟲深入遍歷的網域陣列。
            internal_domains (list[str]): 被視為內部網站的網域陣列。
            crawler_config (dict[str, object] | None): (選填) 要寫入資料庫鎖定的爬蟲設定。
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
            job = session.query(Job).filter(Job.id == job_id).first()
            if job:
                session.expunge(job)
            return job

    # pylint: disable=too-many-locals, too-many-branches, too-many-statements, too-many-nested-blocks
    def run_job(
        self,
        job_id: str,
        crawler_config: dict[str, object] | None = None,
        force: bool = False,
    ) -> None:
        """
        執行指定的爬蟲任務，直到佇列清空或遭到使用者中斷為止。

        Args:
            job_id (str): 欲執行的任務 ID。
            crawler_config (dict[str, object] | None): 爬蟲相關的設定參數。
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

            # 建立共用的執行緒池，避免每個網頁都重新建立與銷毀執行緒而產生額外開銷
            executor = ThreadPoolExecutor(max_workers=5)

            try:
                while True:
                    # 協同暫停檢查：確認任務狀態是否在外部被更改
                    session.expire(job)
                    job = session.query(Job).filter(Job.id == job_id).first()
                    if not job or job.status != "running":
                        logger.info(
                            "偵測到任務狀態變更為 %s，中斷爬取。",
                            job.status if job else "None",
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
                        send_job_status_notification(
                            self.SessionLocal, job_id, "completed"
                        )
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
                        send_job_status_notification(
                            self.SessionLocal, job_id, "completed"
                        )
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
                                ext_link: str,
                            ) -> tuple[str, str | None, int | None, str | None]:
                                """
                                獨立進行單一外部連結的存活與 IP 解析檢查。

                                Args:
                                    ext_link (str): 外部連結網址。

                                Returns:
                                    tuple[str, str | None, int | None, str | None]:
                                        包含 (網址, IP, HTTP 狀態碼, 錯誤訊息)。
                                """
                                tgt_dom = get_domain(ext_link)
                                ip_res = resolve_ip(tgt_dom) if tgt_dom else None
                                code_res, err_res = crawler.check_external_link(
                                    ext_link
                                )
                                return ext_link, ip_res, code_res, err_res

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
                job = session.query(Job).filter(Job.id == job_id).first()
                if job and job.status == "running":
                    job.status = "paused"
                    session.commit()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("任務 %s 發生未預期例外: %s", job_id, e)
                job = session.query(Job).filter(Job.id == job_id).first()
                if job:
                    job.status = "error"
                    session.commit()
                    send_job_status_notification(self.SessionLocal, job_id, "error")
            finally:
                crawler.close()
            executor.shutdown(wait=False)

    def get_all_jobs(
        self, user_id: str | None = None, status: str | None = None
    ) -> list[dict[str, object]]:
        """
        取得所有任務的列表與基本資訊。可透過 user_id 進行過濾。

        Args:
            user_id (str | None): (選填) 若提供，則僅回傳該擁有者的任務。
            status (str | None): (選填) 依據任務狀態進行過濾。

        Returns:
            list[dict[str, object]]: 包含任務基本資訊的字典陣列。
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

    def get_job_report(self, job_id: str) -> dict[str, object] | None:
        """
        取得指定任務的詳細統計報告。

        Args:
            job_id (str): 欲查詢報告的任務 ID。

        Returns:
            dict[str, object] | None: 任務的詳細統計資料。若任務不存在則回傳 None。
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
                    "任務 %s 目前正在執行中，無法直接重置。請先暫停任務再進行重置。",
                    job_id,
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

    def retry_failed_job(self, job_id: str) -> bool:
        """
        局部重試指定任務：將失敗的內部網頁與包含無效外連的網頁重新加入佇列。

        Args:
            job_id (str): 欲局部重試的任務 ID。

        Returns:
            bool: 成功發出重試指令回傳 True，若無法重試則回傳 False。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False

            if job.status == "running":
                logger.error(
                    "任務 %s 目前正在執行中，無法直接重試。請先暫停任務。", job_id
                )
                return False

            job.status = "pending"

            # 1. 找出失敗的外部連結 (DNS 失敗或 HTTP 錯誤)
            failed_ext_links = (
                session.query(ExternalLink)
                .filter(
                    ExternalLink.job_id == job_id,
                    (
                        (ExternalLink.ip_address.is_(None))
                        | (ExternalLink.ip_address == "")
                        | (ExternalLink.http_status_code >= 400)
                        | (ExternalLink.http_status_code.is_(None))
                    ),
                )
                .all()
            )

            source_urls_to_retry = set()
            for ext in failed_ext_links:
                if ext.source_url:
                    source_urls_to_retry.add(ext.source_url)
                session.delete(ext)

            # 2. 將這些失敗外連所屬的母網頁改回 pending (以便重新探測其上的外連)
            if source_urls_to_retry:
                session.query(CrawlQueue).filter(
                    CrawlQueue.job_id == job_id,
                    CrawlQueue.url.in_(source_urls_to_retry),
                ).update(
                    {
                        "status": "pending",
                        "retry_count": 0,
                        "status_code": None,
                        "error_message": None,
                    },
                    synchronize_session=False,
                )

            # 3. 將本身爬取失敗的內部網頁也改回 pending
            session.query(CrawlQueue).filter(
                CrawlQueue.job_id == job_id, CrawlQueue.status == "failed"
            ).update(
                {
                    "status": "pending",
                    "retry_count": 0,
                    "status_code": None,
                    "error_message": None,
                },
                synchronize_session=False,
            )

            session.commit()
            return True
