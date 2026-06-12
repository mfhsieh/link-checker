import sys
import re

with open("crawler/manager.py", "r") as f:
    content = f.read()

# Insert JobRunContext right before class JobManager
context_class = """
@dataclass
class JobRunContext:
    \"\"\"執行中任務的狀態封裝。\"\"\"
    session: Session
    job: Job
    crawler: CrawlerCore
    executor: ThreadPoolExecutor
    crawler_config_dict: dict[str, object]
    checked_links_cache: dict[str, tuple[str | None, int | None, str | None]]
    crawled_count: int
    target_domains_list: list[str]
    trusted_domains_list: list[str]
    max_depth: int | None
    max_pages: int | None
    retries: int
    delay: float
    domain_delays: dict[str, float]
    jitter_ratio: float

"""

content = content.replace("class JobManager:\n", context_class + "class JobManager:\n")


methods = """
    def _initialize_job_run(self, session: Session, job_id: str, force: bool) -> Job | None:
        job: Job | None = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("找不到指定的任務 ID: %s", job_id)
            return None

        if job.status in ["completed", "error"]:
            logger.warning("任務 %s 的狀態已經是 %s，無法再次執行。", job_id, job.status)
            return None

        if job.status == "running" and not force:
            logger.error(
                "任務 %s 目前正在執行中。如果確定前次程序已經意外終止，請加上 -f 或 --force 參數強制接管任務。",
                job_id,
            )
            return None

        job.status = "running"
        session.commit()
        return job

    def _build_run_context(self, session: Session, job: Job, max_workers: int, crawler_config: dict[str, object] | None) -> JobRunContext:
        target_domains_list: list[str] = job.target_domains.split(",") if job.target_domains else []
        trusted_domains_list: list[str] = job.trusted_domains.split(",") if job.trusted_domains else []

        if crawler_config is None:
            if job.config_json:
                try:
                    crawler_config = json.loads(job.config_json)
                    logger.info("已從資料庫成功載入任務 %s 的專屬設定參數。", job.id)
                except json.JSONDecodeError:
                    logger.error("任務 %s 的設定檔解析失敗，將退回使用預設設定。", job.id)
                    crawler_config = {}
            else:
                crawler_config = {}

        timeout = crawler_config.get("timeout", 30)
        connect_timeout = crawler_config.get("connect_timeout", 5.0)
        external_check_timeout = crawler_config.get("external_check_timeout", 10.0)
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
        max_content_length = crawler_config.get("max_content_length", 10485760)
        max_redirects = crawler_config.get("max_redirects", 10)
        jitter_ratio = crawler_config.get("jitter_ratio", 0.2)
        social_domains = crawler_config.get("social_domains", []) or []

        crawled_count = (
            session.query(CrawlQueue)
            .filter(
                CrawlQueue.job_id == job.id,
                (CrawlQueue.status.in_(["completed", "failed", "warning"]))
                | ((CrawlQueue.status == "skip") & (CrawlQueue.status_code.isnot(None))),
            )
            .count()
        )

        checked_links_cache: dict[str, tuple[str | None, int | None, str | None]] = {}
        for ext in session.query(ExternalLink).filter(ExternalLink.job_id == job.id).all():
            if ext.http_status_code is not None or ext.error_message is not None:
                checked_links_cache[ext.target_url] = (
                    ext.ip_address,
                    ext.http_status_code,
                    ext.error_message,
                )

        executor = ThreadPoolExecutor(max_workers=max_workers)
        crawler_config_obj = CrawlerConfig(
            timeout=timeout,
            connect_timeout=connect_timeout,
            external_check_timeout=external_check_timeout,
            ignore_extensions=ignore_extensions,
            mime_type_filter=mime_type_filter,
            ignore_regexes=ignore_regexes,
            user_agent=user_agent,
            ssl_exempt_domains=ssl_exempt_domains,
            proxy_url=proxy_url,
            max_content_length=max_content_length,
            max_redirects=max_redirects,
            social_domains=social_domains,
        )
        crawler = CrawlerCore(config=crawler_config_obj)

        return JobRunContext(
            session=session,
            job=job,
            crawler=crawler,
            executor=executor,
            crawler_config_dict=crawler_config,
            checked_links_cache=checked_links_cache,
            crawled_count=crawled_count,
            target_domains_list=target_domains_list,
            trusted_domains_list=trusted_domains_list,
            max_depth=max_depth,
            max_pages=max_pages,
            retries=retries,
            delay=delay,
            domain_delays=domain_delays,
            jitter_ratio=jitter_ratio,
        )

    def _process_internal_links(self, ctx: JobRunContext, current_url: str, internal_links: list[str], next_depth: int) -> None:
        if ctx.max_depth is None or next_depth <= ctx.max_depth:
            for link in internal_links:
                exists = (
                    ctx.session.query(CrawlQueue)
                    .filter(
                        CrawlQueue.job_id == ctx.job.id,
                        CrawlQueue.url == link,
                    )
                    .first()
                )
                if not exists:
                    new_item = CrawlQueue(
                        job_id=ctx.job.id,
                        url=link,
                        source_url=current_url,
                        status="pending",
                        depth=next_depth,
                    )
                    ctx.session.add(new_item)
        ctx.session.commit()

    def _process_external_links(self, ctx: JobRunContext, current_url: str, external_target_links: list[str]) -> None:
        unique_external_links = list(set(external_target_links))
        links_needing_http_check = []
        for link in unique_external_links:
            exists = (
                ctx.session.query(ExternalLink)
                .filter(
                    ExternalLink.job_id == ctx.job.id,
                    ExternalLink.source_url == current_url,
                    ExternalLink.target_url == link,
                )
                .first()
            )
            if exists:
                continue

            if link in ctx.checked_links_cache:
                cached_ip, cached_code, cached_err = ctx.checked_links_cache[link]
                is_sec = link.startswith("https://")
                new_ext = ExternalLink(
                    job_id=ctx.job.id,
                    source_url=current_url,
                    target_url=link,
                    ip_address=cached_ip,
                    is_secure=is_sec,
                    http_status_code=cached_code,
                    error_message=cached_err,
                )
                ctx.session.add(new_ext)
            else:
                links_needing_http_check.append(link)

        if links_needing_http_check:
            def check_single_link(ext_link: str) -> tuple[str, str | None, int | None, str | None]:
                tgt_dom = get_domain(ext_link)
                ip_res = resolve_ip(tgt_dom) if tgt_dom else None
                code_res, err_res = ctx.crawler.check_external_link(ext_link)
                return ext_link, ip_res, code_res, err_res

            results = list(ctx.executor.map(check_single_link, links_needing_http_check))

            for link, ip, status_code, err_msg in results:
                ctx.checked_links_cache[link] = (ip, status_code, err_msg)
                exists = (
                    ctx.session.query(ExternalLink)
                    .filter(
                        ExternalLink.job_id == ctx.job.id,
                        ExternalLink.source_url == current_url,
                        ExternalLink.target_url == link,
                    )
                    .first()
                )
                if not exists:
                    is_sec = link.startswith("https://")
                    new_ext = ExternalLink(
                        job_id=ctx.job.id,
                        source_url=current_url,
                        target_url=link,
                        ip_address=ip,
                        is_secure=is_sec,
                        http_status_code=status_code,
                        error_message=err_msg,
                    )
                    ctx.session.add(new_ext)

    def _handle_fetch_error(self, ctx: JobRunContext, queue_item: CrawlQueue, current_url: str, e: Exception) -> bool:
        ctx.session.rollback()
        status_code = None
        is_permanent_error = False

        if isinstance(e, httpx.HTTPStatusError):
            status_code = e.response.status_code
            queue_item.status_code = status_code
            logger.error("抓取 %s 時發生 HTTP 狀態碼錯誤 %s", current_url, status_code)
            if status_code in (404, 403):
                is_permanent_error = True
        elif isinstance(e, httpx.RequestError):
            queue_item.status_code = None
            logger.error("抓取 %s 時發生連線請求錯誤: %s", current_url, e)
        else:
            queue_item.status_code = None
            logger.error("抓取 %s 時發生未預期例外: %s", current_url, e)

        if is_permanent_error:
            logger.error("網址 %s 遭遇永久性錯誤 (%s)，直接標記為 failed，不進行重試。", current_url, status_code)
            queue_item.status = "failed"
            queue_item.error_message = f"永久性錯誤: {e}"
            ctx.session.commit()
            ctx.crawled_count += 1
        else:
            if queue_item.retry_count < ctx.retries:
                queue_item.retry_count += 1
                from crawler.manager import _get_domain_delay
                current_domain_delay = _get_domain_delay(current_url, ctx.domain_delays, ctx.delay)
                backoff_delay = current_domain_delay * (2 ** (queue_item.retry_count - 1))
                logger.warning(
                    "處理網址 %s 發生暫時性錯誤，將進行重試 (第 %s/%s 次)。啟用指數退避延遲 %s 秒...",
                    current_url, queue_item.retry_count, ctx.retries, f"{backoff_delay:.1f}"
                )
                ctx.session.commit()
                actual_delay = backoff_delay * random.uniform(1.0 - ctx.jitter_ratio, 1.0 + ctx.jitter_ratio) if ctx.jitter_ratio > 0 else backoff_delay
                time.sleep(actual_delay)
            else:
                logger.error("處理網址 %s 時發生錯誤且已達重試上限", current_url)
                queue_item.status = "failed"
                queue_item.error_message = str(e)
                ctx.session.commit()
                ctx.crawled_count += 1
        return True

    def _process_queue_item(self, ctx: JobRunContext, queue_item: CrawlQueue) -> bool:
        current_url: str = queue_item.url
        logger.info("正在爬取: %s", current_url)
        should_delay = True

        try:
            if ctx.max_depth is not None and queue_item.depth > ctx.max_depth:
                queue_item.status = "skip"
                ctx.session.commit()
                return False

            (
                internal_links,
                external_target_links,
                status_code,
                status,
                request_sent,
                err_msg,
            ) = ctx.crawler.process_url(current_url, ctx.target_domains_list, ctx.trusted_domains_list)

            queue_item.status_code = status_code
            queue_item.status = status
            queue_item.error_message = err_msg
            ctx.session.commit()

            self._process_internal_links(ctx, current_url, internal_links, queue_item.depth + 1)
            self._process_external_links(ctx, current_url, external_target_links)

            queue_item.status = status
            ctx.session.commit()

            should_delay = request_sent
            if request_sent:
                ctx.crawled_count += 1

        except Exception as e:  # pylint: disable=broad-exception-caught
            should_delay = self._handle_fetch_error(ctx, queue_item, current_url, e)

        if should_delay:
            from crawler.manager import _get_domain_delay
            current_domain_delay = _get_domain_delay(current_url, ctx.domain_delays, ctx.delay)
            actual_delay = current_domain_delay * random.uniform(1.0 - ctx.jitter_ratio, 1.0 + ctx.jitter_ratio) if ctx.jitter_ratio > 0 else current_domain_delay
            time.sleep(actual_delay)

        return should_delay

    def run_job(
        self,
        job_id: str,
        crawler_config: dict[str, object] | None = None,
        force: bool = False,
    ) -> None:
        \"\"\"
        執行指定的爬蟲任務，直到佇列清空或遭到使用者中斷為止。

        Args:
            job_id (str): 欲執行的任務 ID。
            crawler_config (dict[str, object] | None): 爬蟲相關的設定參數。
            force (bool): 是否強制接管卡在 running 狀態的任務。
        \"\"\"
        max_workers = int(os.environ.get("CRAWLER_MAX_WORKERS", "5"))
        with self.session_factory() as session:
            job = self._initialize_job_run(session, job_id, force)
            if not job:
                return

            ctx = self._build_run_context(session, job, max_workers, crawler_config)

            try:
                while True:
                    session.expire(job)
                    job = session.query(Job).filter(Job.id == job_id).first()
                    if not job or job.status != "running":
                        logger.info("偵測到任務狀態變更為 %s，中斷爬取。", job.status if job else "None")
                        break

                    if ctx.max_pages is not None and ctx.crawled_count >= ctx.max_pages:
                        logger.info("任務 %s 已達到最大抓取頁數限制 (%s)。優雅結束任務。", job_id, ctx.max_pages)
                        job.status = "completed"
                        session.commit()
                        send_job_status_notification(self.session_factory, job_id, "completed")
                        break

                    queue_item: CrawlQueue | None = (
                        session.query(CrawlQueue)
                        .filter(CrawlQueue.job_id == job_id, CrawlQueue.status == "pending")
                        .order_by(CrawlQueue.id)
                        .first()
                    )

                    if not queue_item:
                        logger.info("任務 %s 已無等待中的網址。任務完成。", job_id)
                        job.status = "completed"
                        session.commit()
                        send_job_status_notification(self.session_factory, job_id, "completed")
                        break

                    self._process_queue_item(ctx, queue_item)

            except KeyboardInterrupt:
                logger.info("任務 %s 已由使用者強制中斷。暫停任務中...", job_id)
                session.rollback()
                job = session.query(Job).filter(Job.id == job_id).first()
                if job and job.status == "running":
                    job.status = "paused"
                    session.commit()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("任務 %s 發生未預期例外: %s", job_id, e)
                session.rollback()
                job = session.query(Job).filter(Job.id == job_id).first()
                if job:
                    job.status = "error"
                    session.commit()
                    send_job_status_notification(self.session_factory, job_id, "error")
            finally:
                ctx.executor.shutdown(wait=True)
                if ctx.crawler:
                    ctx.crawler.close()

    def get_all_jobs("""

pattern = re.compile(r"    # pylint: disable=too-many-locals, too-many-branches, too-many-statements, too-many-nested-blocks\n    def run_job\(.*?def get_all_jobs\(", re.DOTALL)
new_content = pattern.sub(methods, content)

with open("crawler/manager.py", "w") as f:
    f.write(new_content)

print("Refactoring complete.")
