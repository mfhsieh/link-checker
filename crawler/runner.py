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
from sqlalchemy.orm import Session

from crawler.core import CrawlerCore
from crawler.models import CrawlerConfig, CrawlQueue, ExternalLink, Job
from crawler.utils import (
    determine_external_link_status_category,
    determine_internal_link_status_category,
    get_domain,
    resolve_ip,
)

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class JobRunnerState:
    """
    爬蟲任務狀態追蹤資料類別。

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
    """
    從 domain_delays 中尋找符合目前網域的 delay 數值，若無則回傳預設的 delay。

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
        status_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        """
        初始化 JobRunner。

        Args:
            session_factory (Callable[[], Session]): SQLAlchemy Session 工廠。
            job_id (str): 目標任務 ID。
            status_callback (Callable[[str, str], None] | None): 任務狀態變更時的回呼函式。
        """
        self.session_factory = session_factory
        self.job_id = job_id
        self.status_callback = status_callback

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
        """
        開始執行爬蟲任務。

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
            except Exception as e:  # pylint: disable=broad-except
                logger.exception("任務 %s 發生例外: %s", self.job_id, e)
                session.rollback()
                job = session.query(Job).filter(Job.id == self.job_id).first()
                if job:
                    job.status = "error"
                    session.commit()
                    if self.status_callback:
                        self.status_callback(self.job_id, "error")
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

        if job.status == "completed":
            logger.warning("任務 %s 已經完成，無法再次執行。", self.job_id)
            return None

        if job.status in ("running", "error") and not force:
            logger.error(
                "任務 %s 目前狀態為 %s。如果確定前次程序已經意外終止，請加上 -f 或 --force 參數強制接續執行。",
                self.job_id,
                job.status,
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

        # 預熱快取修正：一併快取尚未完成探測的紀錄，標記為 None)
        for ext in session.query(ExternalLink).filter(ExternalLink.job_id == self.job_id).all():
            self.state.checked_links_cache[ext.target_url] = (
                ext.ip_address,
                ext.http_status_code,
                ext.error_message,
            )

        return job

    def _run_loop(self, session: Session, job: Job, crawler: CrawlerCore) -> None:
        """
        任務的執行主迴圈。

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

            if queue_item:
                self._process_item(session, queue_item, crawler)
                continue

            # 若無等待中的內部網址，則檢查是否有 pending 的外部連結需重測
            if self._process_pending_external_links(session, crawler):
                continue

            logger.info("任務 %s 已無等待中的網址或外部連結。任務完成。", self.job_id)
            self._mark_job_completed(session, job)
            break

    def _mark_job_completed(self, session: Session, job: Job) -> None:
        """
        將任務狀態標記為已完成並送出通知。

        Args:
            session (Session): SQLAlchemy Session 實例。
            job (Job): 當前的爬蟲任務物件。
        """
        job.status = "completed"
        session.commit()
        if self.status_callback:
            self.status_callback(self.job_id, "completed")

    def _process_pending_external_links(self, session: Session, crawler: CrawlerCore) -> bool:
        """
        處理被標記為 pending 狀態的外部連結 (非同步重測情境)。

        Args:
            session (Session): SQLAlchemy Session 實例。
            crawler (CrawlerCore): 爬蟲核心引擎。

        Returns:
            bool: 若有處理到 pending 資料則回傳 True，否則回傳 False。
        """
        pending_exts = (
            session.query(ExternalLink)
            .filter(
                ExternalLink.job_id == self.job_id,
                ExternalLink.status_category == "pending",
            )
            .limit(100)
            .all()
        )
        if not pending_exts:
            return False

        unique_urls = list({ext.target_url for ext in pending_exts})
        logger.info("發現 %d 個待重測的外部連結，批次處理中...", len(unique_urls))

        if self.executor:

            def check_single(link: str) -> tuple[str, str | None, int | None, str | None]:
                return self._check_single_link(link, crawler)

            results = list(self.executor.map(check_single, unique_urls))
            res_dict = {res[0]: res for res in results}

            for ext in pending_exts:
                if ext.target_url in res_dict:
                    _, res_ip, res_code, res_err = res_dict[ext.target_url]
                    ext.ip_address = res_ip
                    ext.http_status_code = res_code
                    ext.error_message = res_err
                    ext.is_secure = ext.target_url.startswith("https://")
                    ext.status_category = determine_external_link_status_category(res_ip, res_code)
                    self.state.checked_links_cache[ext.target_url] = (res_ip, res_code, res_err)

            session.commit()
            return True

        return False

    def _process_item(
        self,
        session: Session,
        queue_item: CrawlQueue,
        crawler: CrawlerCore,
    ) -> None:
        """
        處理單一 CrawlQueue 項目。

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
                queue_item.status_category = "skip"
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
            queue_item.status_category = determine_internal_link_status_category(
                queue_item.status, queue_item.status_code, queue_item.error_message
            )
            # 依 Code Review 修正：移除此處的提早 commit，確保資料一致性

            self._handle_internal_links(session, queue_item, result[0])
            self._handle_external_links(session, current_url, result[1], crawler)

            queue_item.status = result[3]
            queue_item.status_category = determine_internal_link_status_category(
                queue_item.status, queue_item.status_code, queue_item.error_message
            )
            # 依 Code Review 修正：統一在此做最後的 commit
            session.commit()

            should_delay = result[4]
            if result[4]:
                self.state.crawled_count += 1

        except httpx.HTTPError as e:
            self._handle_error(session, queue_item, e)
        except Exception as e:  # pylint: disable=broad-exception-caught
            session.rollback()
            logger.error("抓取 %s 時發生未預期錯誤: %s", current_url, e, exc_info=True)
            queue_item.status = "failed"
            queue_item.error_message = f"未預期錯誤: {e}"
            queue_item.status_category = "broken"
            session.commit()

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
        """
        將收集到的內部連結寫入資料庫佇列。

        Args:
            session (Session): SQLAlchemy Session 實例。
            queue_item (CrawlQueue): 當前處理的佇列來源網址物件。
            internal_links (list[str]): 解析出的內部連結陣列。
        """
        next_depth = queue_item.depth + 1
        if self.crawler_config_dict.get("max_depth", None) is None or next_depth <= self.crawler_config_dict.get(
            "max_depth", None
        ):
            if internal_links:
                # 解決 N+1 查詢問題：改用 IN 語法進行批次查詢，找出已存在的內部連結，避免在迴圈內逐一查詢 DB
                existing_urls = {
                    u[0]
                    for u in session.query(CrawlQueue.url)
                    .filter(
                        CrawlQueue.job_id == self.job_id,
                        CrawlQueue.url.in_(internal_links),
                    )
                    .all()
                }
                new_items = []
                for link in internal_links:
                    if link not in existing_urls:
                        existing_urls.add(link)  # 防止同一頁有重複的內連被重複新增
                        new_items.append(
                            CrawlQueue(
                                job_id=self.job_id,
                                url=link,
                                source_url=queue_item.url,
                                status="pending",
                                status_category="pending",
                                is_secure=link.startswith("https://"),
                                depth=next_depth,
                            )
                        )
                if new_items:
                    # 解決 N+1 查詢問題：改用 add_all 進行批次插入 (Batch Insert)
                    session.add_all(new_items)
        # 依 Code Review 修正：此處的 commit 已刪除，由上層 _process_item 統一 commit

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
        if not unique_external_links:
            return links_needing_http_check

        # 解決 N+1 查詢問題：改用 IN 語法進行批次查詢，找出已存在的外部連結，避免在迴圈內逐一查詢 DB
        existing_urls = {
            u[0]
            for u in session.query(ExternalLink.target_url)
            .filter(
                ExternalLink.job_id == self.job_id,
                ExternalLink.source_url == current_url,
                ExternalLink.target_url.in_(unique_external_links),
            )
            .all()
        }

        new_exts = []
        for link in unique_external_links:
            if link in existing_urls:
                continue

            if link in self.state.checked_links_cache:
                cached_data = self.state.checked_links_cache[link]
                is_sec = link.startswith("https://")
                status_cat = determine_external_link_status_category(cached_data[0], cached_data[1])
                new_ext = ExternalLink(
                    job_id=self.job_id,
                    source_url=current_url,
                    target_url=link,
                    target_domain=get_domain(link) or "",
                    ip_address=cached_data[0],
                    is_secure=is_sec,
                    http_status_code=cached_data[1],
                    error_message=cached_data[2],
                    status_category=status_cat,
                )
                new_exts.append(new_ext)
                existing_urls.add(link)  # 防止重複加入
            else:
                links_needing_http_check.append(link)
                existing_urls.add(link)  # 若需 HTTP check 也不要重複加入

        if new_exts:
            # 解決 N+1 查詢問題：改用 add_all 進行批次插入 (Batch Insert)
            session.add_all(new_exts)
        return links_needing_http_check

    def _handle_external_links(
        self,
        session: Session,
        current_url: str,
        external_target_links: list[str],
        crawler: CrawlerCore,
    ) -> None:
        """
        併發處理外部連結存活探測，並將結果寫入資料庫與快取。

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
                link: str,
            ) -> tuple[str, str | None, int | None, str | None]:
                """
                呼叫爬蟲引擎對單一外部連結進行存活探測。

                Args:
                    link (str): 外部連結網址。

                Returns:
                    tuple[str, str | None, int | None, str | None]: (目標網址, IP, 狀態碼, 錯誤訊息)。
                """
                return self._check_single_link(link, crawler)

            results = list(self.executor.map(check_single, needs_check))
            self._save_checked_links(session, current_url, results)

    def _save_checked_links(
        self,
        session: Session,
        current_url: str,
        results: list[tuple[str, str | None, int | None, str | None]],
    ) -> None:
        """
        將探測完畢的外部連結結果保存至資料庫與內部快取記憶體中。

        Args:
            session (Session): SQLAlchemy Session 實例。
            current_url (str): 當前來源網址。
            results (list[tuple[str, str | None, int | None, str | None]]):
                (目標網址, IP, HTTP狀態碼, 錯誤訊息) 構成的結果陣列。
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
                status_cat = determine_external_link_status_category(res_ip, res_code)
                new_ext = ExternalLink(
                    job_id=self.job_id,
                    source_url=current_url,
                    target_url=res_link,
                    target_domain=get_domain(res_link) or "",
                    ip_address=res_ip,
                    is_secure=is_sec,
                    http_status_code=res_code,
                    error_message=res_err,
                    status_category=status_cat,
                )
                session.add(new_ext)

    def _check_single_link(self, link: str, crawler: CrawlerCore) -> tuple[str, str | None, int | None, str | None]:
        """呼叫爬蟲引擎對單一外部連結進行存活探測。

        Args:
            link (str): 外部連結網址。
            crawler (CrawlerCore): 爬蟲核心引擎。

        Returns:
            tuple[str, str | None, int | None, str | None]: (目標網址, IP, 狀態碼, 錯誤訊息)。
        """
        tgt_dom = get_domain(link)
        ip_res = resolve_ip(tgt_dom) if tgt_dom else None
        code_res, err_res = crawler.check_external_link(link)
        return link, ip_res, code_res, err_res

    def _handle_error(self, session: Session, queue_item: CrawlQueue, e: httpx.HTTPError) -> None:
        """
        處理 HTTP 請求過程中的錯誤，套用重試邏輯或標記永久失效。

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
            queue_item.status_category = determine_internal_link_status_category(
                queue_item.status, queue_item.status_code, queue_item.error_message
            )
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
                queue_item.status_category = determine_internal_link_status_category(
                    queue_item.status, queue_item.status_code, queue_item.error_message
                )
                session.commit()
                self.state.crawled_count += 1
