"""
爬蟲任務執行器 (Job Runner) 模組
負責封裝單一爬蟲任務的執行邏輯，包含重試、中斷、狀態更新與併發處理外連。
"""

import json
import logging
import os
import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from crawler.core import CrawlerCore
from crawler.models import CrawlerConfig, CrawlQueue, ExternalLink, Job
from crawler.notifier import send_job_status_notification
from crawler.utils import get_domain, resolve_ip

logger = logging.getLogger(__name__)


@dataclass
class JobRunnerState:
    """爬蟲任務狀態追蹤資料類別。

    Attributes:
        crawled_count (int): 已爬取完成的頁面數量。
        checked_links_cache (dict[str, tuple[str | None, int | None, str | None]]): 外部連結存活檢查的記憶體快取。
        target_domains_list (list[str]): 允許遍歷的目標網域陣列。
        trusted_domains_list (list[str]): 視為信任的網域陣列。
    """

    crawled_count: int = 0
    checked_links_cache: dict[str, tuple[str | None, int | None, str | None]] = field(default_factory=dict)
    target_domains_list: list[str] = field(default_factory=list)
    trusted_domains_list: list[str] = field(default_factory=list)


def _get_domain_delay(url: str, domain_delays: dict[str, float], default_delay: float) -> float:
    """從 domain_delays 中尋找符合目前網域的 delay 數值，若無則回傳預設的 delay。
    支援以子網域完全匹配。

    Args:
        url (str): 當前網址。
        domain_delays (dict[str, float]): 網域為 key、延遲秒數為 value 的字典。
        default_delay (float): 全域預設延遲秒數。

    Returns:
        float: 該網域適用的延遲秒數。
    """
    if not domain_delays:
        return default_delay

    domain = get_domain(url)
    if not domain:
        return default_delay

    matched_delays = []
    for d, delay_val in domain_delays.items():
        if domain == d or domain.endswith("." + d):
            try:
                matched_delays.append((d, float(delay_val)))
            except (ValueError, TypeError):
                continue

    if not matched_delays:
        return default_delay

    matched_delays.sort(key=lambda x: len(x[0]), reverse=True)
    return matched_delays[0][1]


class JobRunner:
    """封裝並執行單一爬蟲任務，避免 run_job 邏輯過於龐大且變數過多。"""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        job_id: str,
    ) -> None:
        """初始化 JobRunner。

        Args:
            session_factory (Callable[[], Session]): SQLAlchemy Session 工廠。
            job_id (str): 目標任務 ID。
        """
        self.session_factory = session_factory
        self.job_id = job_id

        # 以下狀態於 _initialize 中初始化
        self.config: CrawlerConfig | None = None
        self.crawler_config_dict: dict[str, object] = {}
        self.state = JobRunnerState()
        self.executor: ThreadPoolExecutor | None = None

    def execute(
        self,
        crawler_config_param: dict[str, object] | None = None,
        force: bool = False,
        is_api_spawn: bool = False,
    ) -> None:
        """開始執行爬蟲任務。

        Args:
            crawler_config_param (dict[str, object] | None): 爬蟲相關的設定參數。
            force (bool): 是否強制接管卡在 running 狀態的任務。
            is_api_spawn (bool): 是否由 API 背景程序觸發。
        """
        with self.session_factory() as session:
            job = self._initialize(session, crawler_config_param, force, is_api_spawn)
            if not job:
                return

            max_workers = int(os.environ.get("CRAWLER_MAX_WORKERS", "5"))
            self.executor = ThreadPoolExecutor(max_workers=max_workers)
            crawler = None
            try:
                crawler = CrawlerCore(self.config)
                self._run_loop(session, job, crawler)
            except KeyboardInterrupt:
                logger.info("任務 %s 已由使用者強制中斷。暫停任務中...", self.job_id)
                session.rollback()
                job = session.query(Job).filter(Job.id == self.job_id).first()
                if job and job.status == "running":
                    job.status = "paused"
                    session.commit()
            except (httpx.HTTPError, SQLAlchemyError, ValueError, TypeError) as e:
                logger.error("任務 %s 發生例外: %s", self.job_id, e)
                session.rollback()
                job = session.query(Job).filter(Job.id == self.job_id).first()
                if job:
                    job.status = "error"
                    session.commit()
                    send_job_status_notification(self.session_factory, self.job_id, "error")
            finally:
                if self.executor:
                    self.executor.shutdown(wait=True, cancel_futures=True)
                if crawler:
                    crawler.close()

    def get_job_id(self) -> str:
        """取得當前任務 ID。

        Returns:
            str: 任務 ID。
        """
        return self.job_id

    def _initialize(
        self,
        session: Session,
        crawler_config_param: dict[str, object] | None,
        force: bool,
        is_api_spawn: bool = False,
    ) -> Job | None:
        """載入任務並解析配置。若任務狀態無法執行則回傳 None。

        Args:
            session (Session): SQLAlchemy Session 實例。
            crawler_config_param (dict[str, object] | None): 傳入的爬蟲參數設定字典。
            force (bool): 是否強制接管。
            is_api_spawn (bool): 是否為 API 生成程序的背景呼叫。

        Returns:
            Job | None: 初始化成功的任務物件，若無法執行則回傳 None。
        """
        job: Job | None = session.query(Job).filter(Job.id == self.job_id).first()
        if not job:
            logger.error("找不到指定的任務 ID: %s", self.job_id)
            return None

        if job.status in ["completed", "error"]:
            logger.warning("任務 %s 的狀態已經是 %s，無法再次執行。", self.job_id, job.status)
            return None

        if job.status == "running" and not force:
            logger.error(
                "任務 %s 目前正在執行中。如果確定前次程序已經意外終止，請加上 -f 或 --force 參數強制接管任務。",
                self.job_id,
            )
            return None

        if is_api_spawn and job.status != "starting" and not force:
            logger.info(
                "任務 %s 當前狀態為 %s，並非預期的 starting。表示任務可能已在啟動階段被暫停，取消執行。",
                self.job_id,
                job.status,
            )
            return None

        job.status = "running"
        session.commit()

        self.state.target_domains_list = job.target_domains.split(",") if job.target_domains else []
        self.state.trusted_domains_list = job.trusted_domains.split(",") if job.trusted_domains else []

        crawler_config = crawler_config_param
        if crawler_config is None:
            if job.config_json:
                try:
                    crawler_config = json.loads(job.config_json)
                    logger.info("已從資料庫成功載入任務 %s 的專屬設定參數。", self.job_id)
                except json.JSONDecodeError:
                    logger.error("任務 %s 的設定檔解析失敗，將退回使用預設設定。", self.job_id)
                    crawler_config = {}
            else:
                crawler_config = {}

        self.crawler_config_dict = crawler_config

        # 建立 config
        self.config = CrawlerConfig(
            timeout=crawler_config.get("timeout", 30),
            connect_timeout=crawler_config.get("connect_timeout", 5.0),
            external_check_timeout=crawler_config.get("external_check_timeout", 10.0),
            ignore_extensions=crawler_config.get("ignore_extensions", None),
            mime_type_filter=crawler_config.get("mime_type_filter", None),
            ignore_regexes=crawler_config.get("ignore_regexes", None),
            user_agent=crawler_config.get("user_agent", None),
            ssl_exempt_domains=crawler_config.get("ssl_exempt_domains", []) or [],
            proxy_url=crawler_config.get("proxy_url", None),
            max_content_length=crawler_config.get("max_content_length", 10485760),
            max_redirects=crawler_config.get("max_redirects", 10),
            social_domains=crawler_config.get("social_domains", []) or [],
        )

        self.state.crawled_count = (
            session.query(CrawlQueue)
            .filter(
                CrawlQueue.job_id == self.job_id,
                (CrawlQueue.status.in_(["completed", "failed", "warning"]))
                | ((CrawlQueue.status == "skip") & (CrawlQueue.status_code.isnot(None))),
            )
            .count()
        )

        # 預熱快取
        for ext in session.query(ExternalLink).filter(ExternalLink.job_id == self.job_id).all():
            if ext.http_status_code is not None or ext.error_message is not None:
                self.state.checked_links_cache[ext.target_url] = (
                    ext.ip_address,
                    ext.http_status_code,
                    ext.error_message,
                )

        return job

    def _run_loop(self, session: Session, job: Job, crawler: CrawlerCore) -> None:
        """任務的執行主迴圈。

        Args:
            session (Session): SQLAlchemy Session 實例。
            job (Job): 當前的爬蟲任務物件。
            crawler (CrawlerCore): 初始化的爬蟲核心引擎。
        """
        while True:
            session.expire(job)
            job = session.query(Job).filter(Job.id == self.job_id).first()
            if not job or job.status != "running":
                logger.info("偵測到任務狀態變更為 %s，中斷爬取。", job.status if job else "None")
                break

            if self.crawler_config_dict.get(
                "max_pages", None
            ) is not None and self.state.crawled_count >= self.crawler_config_dict.get("max_pages", None):
                logger.info(
                    "任務 %s 已達到最大抓取頁數限制 (%s)。優雅結束任務。",
                    self.job_id,
                    self.crawler_config_dict.get("max_pages", None),
                )
                self._mark_job_completed(session, job)
                break

            queue_item: CrawlQueue | None = (
                session.query(CrawlQueue)
                .filter(CrawlQueue.job_id == self.job_id, CrawlQueue.status == "pending")
                .order_by(CrawlQueue.id)
                .first()
            )

            if not queue_item:
                logger.info("任務 %s 已無等待中的網址。任務完成。", self.job_id)
                self._mark_job_completed(session, job)
                break

            self._process_item(session, queue_item, crawler)

    def _mark_job_completed(self, session: Session, job: Job) -> None:
        """將任務狀態標記為已完成並送出通知。

        Args:
            session (Session): SQLAlchemy Session 實例。
            job (Job): 當前的爬蟲任務物件。
        """
        job.status = "completed"
        session.commit()
        send_job_status_notification(self.session_factory, self.job_id, "completed")

    def _process_item(
        self,
        session: Session,
        queue_item: CrawlQueue,
        crawler: CrawlerCore,
    ) -> None:
        """處理單一 CrawlQueue 項目。

        Args:
            session (Session): SQLAlchemy Session 實例。
            queue_item (CrawlQueue): 當前準備處理的佇列物件。
            crawler (CrawlerCore): 爬蟲核心引擎。
        """
        current_url: str = queue_item.url
        logger.info("正在爬取: %s", current_url)

        should_delay = True
        try:
            if self.crawler_config_dict.get(
                "max_depth", None
            ) is not None and queue_item.depth > self.crawler_config_dict.get("max_depth", None):
                queue_item.status = "skip"
                session.commit()
                return

            # 呼叫爬蟲核心取得結果 (回傳：internal_links, external_target_links, status_code, status, request_sent, err_msg)
            result = crawler.process_url(
                current_url,
                self.state.target_domains_list,
                self.state.trusted_domains_list,
            )

            queue_item.status_code = result[2]
            queue_item.status = result[3]
            queue_item.error_message = result[5]
            session.commit()

            self._handle_internal_links(session, queue_item, result[0])
            self._handle_external_links(session, current_url, result[1], crawler)

            queue_item.status = result[3]
            session.commit()

            should_delay = result[4]
            if result[4]:
                self.state.crawled_count += 1

        except httpx.HTTPError as e:
            self._handle_error(session, queue_item, e)

        if should_delay:
            current_domain_delay = _get_domain_delay(
                current_url,
                self.crawler_config_dict.get("domain_delays", {}),
                self.crawler_config_dict.get("delay", 1.0),
            )
            actual_delay = (
                current_domain_delay
                * random.uniform(
                    1.0 - self.crawler_config_dict.get("jitter_ratio", 0.2),
                    1.0 + self.crawler_config_dict.get("jitter_ratio", 0.2),
                )
                if self.crawler_config_dict.get("jitter_ratio", 0.2) > 0
                else current_domain_delay
            )
            time.sleep(actual_delay)

    def _handle_internal_links(self, session: Session, queue_item: CrawlQueue, internal_links: list[str]) -> None:
        """將收集到的內部連結寫入資料庫佇列。

        Args:
            session (Session): SQLAlchemy Session 實例。
            queue_item (CrawlQueue): 當前處理的佇列來源網址物件。
            internal_links (list[str]): 解析出的內部連結陣列。
        """
        next_depth = queue_item.depth + 1
        if self.crawler_config_dict.get("max_depth", None) is None or next_depth <= self.crawler_config_dict.get(
            "max_depth", None
        ):
            for link in internal_links:
                exists = (
                    session.query(CrawlQueue)
                    .filter(
                        CrawlQueue.job_id == self.job_id,
                        CrawlQueue.url == link,
                    )
                    .first()
                )
                if not exists:
                    new_item = CrawlQueue(
                        job_id=self.job_id,
                        url=link,
                        source_url=queue_item.url,
                        status="pending",
                        depth=next_depth,
                    )
                    session.add(new_item)
        session.commit()

    def _prepare_external_links(
        self,
        session: Session,
        current_url: str,
        unique_external_links: list[str],
    ) -> list[str]:
        """過濾出需要進行存活探測的全新外部連結（利用快取去重）。

        Args:
            session (Session): SQLAlchemy Session 實例。
            current_url (str): 當前來源網址。
            unique_external_links (list[str]): 本頁取得的獨立外部連結清單。

        Returns:
            list[str]: 尚未被快取或處理過的外部連結清單，需進一步發送 HTTP 探測。
        """
        links_needing_http_check = []
        for link in unique_external_links:
            exists = (
                session.query(ExternalLink)
                .filter(
                    ExternalLink.job_id == self.job_id,
                    ExternalLink.source_url == current_url,
                    ExternalLink.target_url == link,
                )
                .first()
            )
            if exists:
                continue

            if link in self.state.checked_links_cache:
                cached_data = self.state.checked_links_cache[link]
                is_sec = link.startswith("https://")
                new_ext = ExternalLink(
                    job_id=self.job_id,
                    source_url=current_url,
                    target_url=link,
                    ip_address=cached_data[0],
                    is_secure=is_sec,
                    http_status_code=cached_data[1],
                    error_message=cached_data[2],
                )
                session.add(new_ext)
            else:
                links_needing_http_check.append(link)
        return links_needing_http_check

    def _handle_external_links(
        self,
        session: Session,
        current_url: str,
        external_target_links: list[str],
        crawler: CrawlerCore,
    ) -> None:
        """併發處理外部連結存活探測，並將結果寫入資料庫與快取。

        Args:
            session (Session): SQLAlchemy Session 實例。
            current_url (str): 當前來源網址。
            external_target_links (list[str]): 待處理的外部連結陣列。
            crawler (CrawlerCore): 爬蟲核心引擎。
        """
        unique_links = list(set(external_target_links))
        needs_check = self._prepare_external_links(session, current_url, unique_links)

        if needs_check and self.executor:

            def check_single(
                ext_link: str,
            ) -> tuple[str, str | None, int | None, str | None]:
                """
                呼叫爬蟲引擎對單一外部連結進行存活探測。

                Args:
                    ext_link (str): 外部連結網址。

                Returns:
                    tuple[str, str | None, int | None, str | None]: (目標網址, IP, 狀態碼, 錯誤訊息)。
                """
                return self._check_single_link(ext_link, crawler)

            results = list(self.executor.map(check_single, needs_check))
            self._save_checked_links(session, current_url, results)

    def _save_checked_links(
        self,
        session: Session,
        current_url: str,
        results: list[tuple[str, str | None, int | None, str | None]],
    ) -> None:
        """將探測完畢的外部連結結果保存至資料庫與內部快取記憶體中。

        Args:
            session (Session): SQLAlchemy Session 實例。
            current_url (str): 當前來源網址。
            results (list[tuple]): (目標網址, IP, HTTP狀態碼, 錯誤訊息) 構成的結果陣列。
        """
        for res_link, res_ip, res_code, res_err in results:
            self.state.checked_links_cache[res_link] = (res_ip, res_code, res_err)
            exists = (
                session.query(ExternalLink)
                .filter(
                    ExternalLink.job_id == self.job_id,
                    ExternalLink.source_url == current_url,
                    ExternalLink.target_url == res_link,
                )
                .first()
            )
            if not exists:
                is_sec = res_link.startswith("https://")
                new_ext = ExternalLink(
                    job_id=self.job_id,
                    source_url=current_url,
                    target_url=res_link,
                    ip_address=res_ip,
                    is_secure=is_sec,
                    http_status_code=res_code,
                    error_message=res_err,
                )
                session.add(new_ext)

    def _check_single_link(self, ext_link: str, crawler: CrawlerCore) -> tuple[str, str | None, int | None, str | None]:
        """呼叫爬蟲引擎對單一外部連結進行存活探測。

        Args:
            ext_link (str): 外部連結網址。
            crawler (CrawlerCore): 爬蟲核心引擎。

        Returns:
            tuple[str, str | None, int | None, str | None]: (目標網址, IP, 狀態碼, 錯誤訊息)。
        """
        tgt_dom = get_domain(ext_link)
        ip_res = resolve_ip(tgt_dom) if tgt_dom else None
        code_res, err_res = crawler.check_external_link(ext_link)
        return ext_link, ip_res, code_res, err_res

    def _handle_error(self, session: Session, queue_item: CrawlQueue, e: httpx.HTTPError) -> None:
        """處理 HTTP 請求過程中的錯誤，套用重試邏輯或標記永久失效。

        Args:
            session (Session): SQLAlchemy Session 實例。
            queue_item (CrawlQueue): 發生錯誤的佇列物件。
            e (httpx.HTTPError): 捕捉到的 HTTPX 例外。
        """
        session.rollback()
        current_url = queue_item.url
        status_code = None
        is_permanent_error = False

        if isinstance(e, httpx.HTTPStatusError):
            status_code = e.response.status_code
            queue_item.status_code = status_code
            logger.error("抓取 %s 時發生 HTTP 狀態碼錯誤 %s", current_url, status_code)
            if status_code in (404, 403):
                is_permanent_error = True
        else:
            queue_item.status_code = None
            logger.error("抓取 %s 時發生連線請求錯誤: %s", current_url, e)

        if is_permanent_error:
            logger.error(
                "網址 %s 遭遇永久性錯誤 (%s)，直接標記為 failed，不進行重試。",
                current_url,
                status_code,
            )
            queue_item.status = "failed"
            queue_item.error_message = f"永久性錯誤: {e}"
            session.commit()
            self.state.crawled_count += 1
        else:
            if queue_item.retry_count < self.crawler_config_dict.get("retries", 3):
                queue_item.retry_count += 1
                current_domain_delay = _get_domain_delay(
                    current_url,
                    self.crawler_config_dict.get("domain_delays", {}),
                    self.crawler_config_dict.get("delay", 1.0),
                )
                backoff_delay = current_domain_delay * (2 ** (queue_item.retry_count - 1))
                logger.warning(
                    "處理網址 %s 發生暫時性錯誤，將進行重試 (第 %s/%s 次)。啟用指數退避延遲 %s 秒...",
                    current_url,
                    queue_item.retry_count,
                    self.crawler_config_dict.get("retries", 3),
                    f"{backoff_delay:.1f}",
                )
                session.commit()
                actual_delay = (
                    backoff_delay
                    * random.uniform(
                        1.0 - self.crawler_config_dict.get("jitter_ratio", 0.2),
                        1.0 + self.crawler_config_dict.get("jitter_ratio", 0.2),
                    )
                    if self.crawler_config_dict.get("jitter_ratio", 0.2) > 0
                    else backoff_delay
                )
                time.sleep(actual_delay)
            else:
                logger.error("處理網址 %s 時發生錯誤且已達重試上限", current_url)
                queue_item.status = "failed"
                queue_item.error_message = str(e)
                session.commit()
                self.state.crawled_count += 1
