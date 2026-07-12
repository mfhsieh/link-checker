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
from typing import cast

import httpx
from cachetools import LRUCache
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.events import SystemEvent
from crawler.config_utils import DEFAULT_GLOBAL_CONFIG
from crawler.core import CrawlerCore
from crawler.models import CrawlerConfig, CrawlQueue, ExternalLink, Job
from crawler.utils import (
    bulk_insert_ignore,
    determine_external_link_status_category,
    determine_internal_link_status_category,
    get_domain,
    resolve_ip,
)

_crawler_def = DEFAULT_GLOBAL_CONFIG.get("crawler", {})
_DEF = _crawler_def if isinstance(_crawler_def, dict) else {}

logger: logging.Logger = logging.getLogger(__name__)

# 外部連結狀態快取的最大數量限制，避免發生 OOM (Out Of Memory)
DEFAULT_LRU_CACHE_MAXSIZE: int = 1000

# 爬蟲主迴圈查詢資料庫任務狀態（如：是否被暫停）的間隔時間 (秒)
STATUS_CHECK_INTERVAL: float = 10.0


@dataclass
class JobRunnerState:  # pylint: disable=too-many-instance-attributes
    """
    爬蟲任務狀態追蹤資料類別。

    Attributes:
        crawled_count (int): 已爬取完成的頁面數量。
        checked_links_cache (dict[str, tuple[str | None, int | None, str | None]]): 外部連結存活檢查的記憶體快取。
        target_domains_list (list[str]): 允許遍歷的目標網域陣列。
        trusted_domains_list (list[str]): 視為信任的網域陣列。
    """

    crawled_count: int = 0
    checked_links_cache: LRUCache = field(default_factory=lambda: LRUCache(maxsize=DEFAULT_LRU_CACHE_MAXSIZE))
    target_domains_list: list[str] = field(default_factory=list)
    trusted_domains_list: list[str] = field(default_factory=list)

    # 用於在記憶體中追蹤任務進度，避免反覆 O(N) 查詢資料庫
    queue_total: int = 0
    queue_completed: int = 0
    queue_warning: int = 0
    queue_pending: int = 0
    queue_failed: int = 0
    queue_skipped: int = 0
    external_links_total: int = 0
    last_flush_time: float = 0.0


def _get_domain_delay(domain: str, domain_delays: dict[str, float], default_delay: float) -> float:
    """
    從 domain_delays 中尋找符合目前網域的 delay 數值，若無則回傳預設的 delay。

    支援以子網域完全匹配。

    Args:
        domain (str): 當前網域。
        domain_delays (dict[str, float]): 網域為 key、延遲秒數為 value 的字典。
        default_delay (float): 全域預設延遲秒數。

    Returns:
        float: 該網域適用的延遲秒數。
    """
    if not domain_delays:
        return default_delay

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
        on_event_callback: Callable[..., None] | None = None,
    ) -> None:
        """
        初始化 JobRunner。

        Args:
            session_factory (Callable[[], Session]): SQLAlchemy Session 工廠。
            job_id (str): 目標任務 ID。
            on_event_callback (Callable[..., None] | None): 事件回呼函式。
        """
        self.session_factory = session_factory
        self.job_id = job_id
        self.on_event_callback = on_event_callback

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
                logger.critical("[JOB_CRASH_ALERT] 任務 %s 發生例外: %s", self.job_id, e, exc_info=True)
                session.rollback()
                job = session.query(Job).filter(Job.id == self.job_id).first()
                if job:
                    job.status = "error"
                    session.commit()
                    if self.on_event_callback:
                        self.on_event_callback(SystemEvent.JOB_STATUS_CHANGED, job_id=self.job_id, status="error")
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
            timeout=cast(int, crawler_config.get("timeout", 30)),
            connect_timeout=cast(float, crawler_config.get("connect_timeout", 5.0)),
            external_check_timeout=cast(float, crawler_config.get("external_check_timeout", 10.0)),
            ignore_extensions=cast(
                list[str], crawler_config.get("ignore_extensions", _DEF.get("ignore_extensions", []))
            ),
            mime_type_filter=cast(
                dict[str, object], crawler_config.get("mime_type_filter", _DEF.get("mime_type_filter", {}))
            ),
            ignore_regexes=cast(list[str], crawler_config.get("ignore_regexes", _DEF.get("ignore_regexes", []))),
            user_agent=cast(str | None, crawler_config.get("user_agent", None)),
            ssl_exempt_domains=cast(
                list[str], crawler_config.get("ssl_exempt_domains", _DEF.get("ssl_exempt_domains", []))
            ),
            proxy_url=cast(str | None, crawler_config.get("proxy_url", None)),
            max_content_length=cast(int, crawler_config.get("max_content_length", 10485760)),
            max_redirects=cast(int, crawler_config.get("max_redirects", 10)),
            social_domains=cast(list[str], crawler_config.get("social_domains", _DEF.get("social_domains", []))),
        )

        from sqlalchemy import case  # pylint: disable=import-outside-toplevel
        from sqlalchemy.sql.functions import count as sql_count  # pylint: disable=import-outside-toplevel
        from sqlalchemy.sql.functions import sum as sql_sum  # pylint: disable=import-outside-toplevel

        # pylint: disable=duplicate-code
        queue_stats = (
            session.query(
                sql_count(CrawlQueue.id).label("total"),
                sql_sum(case((CrawlQueue.status == "completed", 1), else_=0)).label("completed"),
                sql_sum(case((CrawlQueue.status == "warning", 1), else_=0)).label("warning"),
                sql_sum(case((CrawlQueue.status == "pending", 1), else_=0)).label("pending"),
                sql_sum(case((CrawlQueue.status == "failed", 1), else_=0)).label("failed"),
                sql_sum(case((CrawlQueue.status == "skip", 1), else_=0)).label("skipped"),
            )
            .filter(CrawlQueue.job_id == self.job_id)
            .first()
        )

        self.state.queue_total = int(queue_stats.total) if queue_stats and queue_stats.total else 0
        self.state.queue_completed = int(queue_stats.completed) if queue_stats and queue_stats.completed else 0
        self.state.queue_warning = int(queue_stats.warning) if queue_stats and queue_stats.warning else 0
        self.state.queue_pending = int(queue_stats.pending) if queue_stats and queue_stats.pending else 0
        self.state.queue_failed = int(queue_stats.failed) if queue_stats and queue_stats.failed else 0
        self.state.queue_skipped = int(queue_stats.skipped) if queue_stats and queue_stats.skipped else 0

        self.state.external_links_total = session.query(ExternalLink).filter(ExternalLink.job_id == self.job_id).count()

        self.state.crawled_count = self.state.queue_completed + self.state.queue_failed + self.state.queue_warning
        self.state.last_flush_time = time.time()

        # 已移除預熱快取修正：不再全量查詢 ExternalLink 並快取，改於 _prepare_external_links 延遲載入以防 OOM。

        return job

    def _run_loop(self, session: Session, job: Job, crawler: CrawlerCore) -> None:
        """
        任務的執行主迴圈。

        Args:
            session (Session): SQLAlchemy Session 實例。
            job (Job): 當前的爬蟲任務物件。
            crawler (CrawlerCore): 初始化的爬蟲核心引擎。
        """
        last_status_check_time = time.time()
        self.state.last_flush_time = time.time()

        while True:
            current_time = time.time()
            # 節流機制：每隔 N 秒才真正向資料庫查詢一次狀態，避免產生大量不必要的 SELECT 查詢開銷
            if current_time - last_status_check_time >= STATUS_CHECK_INTERVAL:
                session.expire(job)
                fetched_job = session.query(Job).filter(Job.id == self.job_id).first()
                if not fetched_job or fetched_job.status != "running":
                    logger.info("偵測到任務狀態變更為 %s，中斷爬取。", fetched_job.status if fetched_job else "None")
                    break
                job = fetched_job
                last_status_check_time = current_time

            if current_time - self.state.last_flush_time >= 3.0:
                self._flush_progress(session, job)
                self.state.last_flush_time = current_time

            max_pages = cast(int | None, self.crawler_config_dict.get("max_pages"))
            if max_pages is not None and self.state.crawled_count >= max_pages:
                logger.info(
                    "任務 %s 已達到最大抓取頁數限制 (%s)。優雅結束任務。",
                    self.job_id,
                    max_pages,
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

    def _flush_progress(self, session: Session, job: Job) -> None:
        """將記憶體中的進度狀態轉為 JSON 寫入資料庫，供 Web API 讀取。"""
        progress_dict = {
            "queue": {
                "total": self.state.queue_total,
                "completed": self.state.queue_completed,
                "warning": self.state.queue_warning,
                "skipped": self.state.queue_skipped,
                "pending": self.state.queue_pending,
                "failed": self.state.queue_failed,
            },
            "external_links": self.state.external_links_total,
        }
        job.progress_stats = json.dumps(progress_dict)
        session.commit()

    def _mark_job_completed(self, session: Session, job: Job) -> None:
        """
        將任務狀態標記為已完成並送出通知。

        Args:
            session (Session): SQLAlchemy Session 實例。
            job (Job): 當前的爬蟲任務物件。
        """
        self._flush_progress(session, job)
        job.status = "completed"
        session.commit()
        if self.on_event_callback:
            self.on_event_callback(SystemEvent.JOB_STATUS_CHANGED, job_id=self.job_id, status="completed")

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

    # pylint: disable=too-many-locals, too-many-statements
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
            max_depth = cast(int | None, self.crawler_config_dict.get("max_depth"))
            if max_depth is not None and queue_item.depth > max_depth:
                queue_item.status = "skip"
                queue_item.status_category = "skip"
                session.commit()
                self.state.queue_pending -= 1
                self.state.queue_skipped += 1
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

            delta_pending, delta_total = self._handle_internal_links(session, queue_item, result[0])
            delta_ext = self._handle_external_links(session, current_url, result[1], crawler)

            queue_item.status = result[3]
            queue_item.status_category = determine_internal_link_status_category(
                queue_item.status, queue_item.status_code, queue_item.error_message
            )
            # 依 Code Review 修正：統一在此做最後的 commit
            session.commit()

            # 在 commit 成功後才更新 In-Memory 進度，避免 rollback 導致數字失真
            self.state.queue_pending -= 1
            if result[3] == "completed":
                self.state.queue_completed += 1
            elif result[3] == "warning":
                self.state.queue_warning += 1
            elif result[3] == "failed":
                self.state.queue_failed += 1
            elif result[3] == "skip":
                self.state.queue_skipped += 1

            self.state.queue_pending += delta_pending
            self.state.queue_total += delta_total
            self.state.external_links_total += delta_ext

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

            self.state.queue_pending -= 1
            self.state.queue_failed += 1

        if should_delay:
            domain = get_domain(current_url) or ""
            domain_delays: dict[str, float] = cast(dict[str, float], self.crawler_config_dict.get("domain_delays", {}))
            base_delay = cast(float, self.crawler_config_dict.get("delay", 0.0))
            delay = _get_domain_delay(
                domain,
                domain_delays,
                base_delay,
            )

            jitter_ratio = cast(float, self.crawler_config_dict.get("jitter_ratio", 0.0))
            min_delay = delay - (delay * jitter_ratio)
            max_delay = delay + (delay * jitter_ratio)
            actual_delay = random.uniform(min_delay, max_delay)

            min_config = cast(float, self.crawler_config_dict.get("min_delay", 0.0))
            actual_delay = max(actual_delay, min_config)
            time.sleep(actual_delay)

    def _handle_internal_links(
        self, session: Session, queue_item: CrawlQueue, internal_links: list[str]
    ) -> tuple[int, int]:
        """
        將收集到的內部連結寫入資料庫佇列。

        Args:
            session (Session): SQLAlchemy Session 實例。
            queue_item (CrawlQueue): 當前處理的佇列來源網址物件。
            internal_links (list[str]): 解析出的內部連結陣列。

        Returns:
            tuple[int, int]: (新增的待處理數量, 新增的總數量)
        """
        next_depth = queue_item.depth + 1
        max_depth = cast(int | None, self.crawler_config_dict.get("max_depth"))
        if max_depth is None or next_depth <= max_depth:
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
        new_items_count = len(new_items) if "new_items" in locals() and new_items else 0
        return new_items_count, new_items_count

    def _prepare_external_links(
        self,
        session: Session,
        current_url: str,
        unique_external_links: list[str],
    ) -> tuple[list[str], int]:
        """過濾出需要進行存活探測的全新外部連結（利用快取去重）。

        Args:
            session (Session): SQLAlchemy Session 實例。
            current_url (str): 當前來源網址。
            unique_external_links (list[str]): 本頁取得的獨立外部連結清單。

        Returns:
            tuple[list[str], int]: (需進一步發送 HTTP 探測的網址清單, 本次新增的外部連結總數)
        """
        links_needing_http_check: list[str] = []
        if not unique_external_links:
            return links_needing_http_check, 0

        # 解決 N+1 查詢問題：改用 IN 語法進行批次查詢，找出已存在的外部連結，避免在迴圈內逐一查詢 DB
        existing_urls_for_page = {
            u[0]
            for u in session.query(ExternalLink.target_url)
            .filter(
                ExternalLink.job_id == self.job_id,
                ExternalLink.source_url == current_url,
                ExternalLink.target_url.in_(unique_external_links),
            )
            .all()
        }

        links_to_process = [link for link in unique_external_links if link not in existing_urls_for_page]
        links_not_in_cache = [link for link in links_to_process if link not in self.state.checked_links_cache]

        if links_not_in_cache:
            db_checked_links = (
                session.query(
                    ExternalLink.target_url,
                    ExternalLink.ip_address,
                    ExternalLink.http_status_code,
                    ExternalLink.error_message,
                )
                .filter(
                    ExternalLink.job_id == self.job_id,
                    ExternalLink.target_url.in_(links_not_in_cache),
                )
                .all()
            )
            for target_url, ip, status_code, err_msg in db_checked_links:
                self.state.checked_links_cache[target_url] = (ip, status_code, err_msg)

        new_exts = []
        existing_urls_set = set()

        for link in links_to_process:
            if link in existing_urls_set:
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
                existing_urls_set.add(link)
            else:
                links_needing_http_check.append(link)
                existing_urls_set.add(link)

        if new_exts:
            # 解決 N+1 查詢問題：改用 add_all 進行批次插入 (Batch Insert)
            session.add_all(new_exts)
        return links_needing_http_check, len(new_exts)

    def _handle_external_links(
        self,
        session: Session,
        current_url: str,
        external_target_links: list[str],
        crawler: CrawlerCore,
    ) -> int:
        """
        併發處理外部連結存活探測，並將結果寫入資料庫與快取。

        Args:
            session (Session): SQLAlchemy Session 實例。
            current_url (str): 當前來源網址。
            external_target_links (list[str]): 待處理的外部連結陣列。
            crawler (CrawlerCore): 爬蟲核心引擎。

        Returns:
            int: 本次新增的外部連結總數
        """
        unique_links = list(set(external_target_links))
        needs_check, new_exts_count = self._prepare_external_links(session, current_url, unique_links)

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

        return new_exts_count

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
        mappings: list[dict[str, object]] = []
        for res_link, res_ip, res_code, res_err in results:
            self.state.checked_links_cache[res_link] = (res_ip, res_code, res_err)
            is_sec = res_link.startswith("https://")
            status_cat = determine_external_link_status_category(res_ip, res_code)
            mappings.append(
                {
                    "job_id": self.job_id,
                    "source_url": current_url,
                    "target_url": res_link,
                    "target_domain": get_domain(res_link) or "",
                    "ip_address": res_ip,
                    "is_secure": is_sec,
                    "http_status_code": res_code,
                    "error_message": res_err,
                    "status_category": status_cat,
                }
            )

        if mappings:
            try:
                bulk_insert_ignore(
                    session=session,
                    model=ExternalLink,
                    mappings=mappings,
                    index_elements=["job_id", "source_url", "target_url"],
                )
            except SQLAlchemyError as e:
                logger.critical(
                    "[DATA_LOSS_ALERT] 批次儲存外部連結失敗 (batch save external links): %s", e, exc_info=True
                )

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

            self.state.queue_pending -= 1
            self.state.queue_failed += 1
            self.state.crawled_count += 1
        else:
            retries = cast(int, self.crawler_config_dict.get("retries", 3))
            if queue_item.retry_count < retries:
                queue_item.retry_count += 1
                domain_delays: dict[str, float] = cast(
                    dict[str, float], self.crawler_config_dict.get("domain_delays", {})
                )
                base_delay = cast(float, self.crawler_config_dict.get("delay", 1.0))
                current_domain_delay = _get_domain_delay(
                    get_domain(current_url) or "",
                    domain_delays,
                    base_delay,
                )
                backoff_delay = current_domain_delay * (2 ** (queue_item.retry_count - 1))
                logger.warning(
                    "處理網址 %s 發生暫時性錯誤，將進行重試 (第 %s/%s 次)。啟用指數退避延遲 %s 秒...",
                    current_url,
                    queue_item.retry_count,
                    retries,
                    f"{backoff_delay:.1f}",
                )
                session.commit()

                jitter_ratio = cast(float, self.crawler_config_dict.get("jitter_ratio", 0.2))
                actual_delay = (
                    backoff_delay
                    * random.uniform(
                        1.0 - jitter_ratio,
                        1.0 + jitter_ratio,
                    )
                    if jitter_ratio > 0
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

                self.state.queue_pending -= 1
                self.state.queue_failed += 1
                self.state.crawled_count += 1
