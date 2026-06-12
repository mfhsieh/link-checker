import sys
import re

with open("crawler/manager.py", "r") as f:
    content = f.read()

# 1. Update JobRunContext to remove extra fields
pattern_ctx = re.compile(r"    target_domains_list: list\[str\]\n    trusted_domains_list: list\[str\]\n    max_depth: int \| None.*?jitter_ratio: float\n", re.DOTALL)
content = pattern_ctx.sub("    target_domains_list: list[str]\n    trusted_domains_list: list[str]\n", content)

# 2. Update _build_run_context to avoid local variables and use crawler_config
pattern_build = re.compile(r"        timeout = crawler_config\.get\(.*?CrawlerCore\(config=crawler_config_obj\)", re.DOTALL)
replacement_build = """        crawled_count = (
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
        crawler = CrawlerCore(config=crawler_config_obj)"""

content = pattern_build.sub(replacement_build, content)

# Fix the return of _build_run_context
pattern_return = re.compile(r"            target_domains_list=target_domains_list,\n            trusted_domains_list=trusted_domains_list,\n            max_depth=max_depth,.*?jitter_ratio=jitter_ratio,\n        \)", re.DOTALL)
content = pattern_return.sub("            target_domains_list=target_domains_list,\n            trusted_domains_list=trusted_domains_list,\n        )", content)


# 3. Replace ctx.max_depth, ctx.retries etc with ctx.crawler_config_dict.get
content = content.replace("ctx.max_depth", 'ctx.crawler_config_dict.get("max_depth", None)')
content = content.replace("ctx.max_pages", 'ctx.crawler_config_dict.get("max_pages", None)')
content = content.replace("ctx.retries", 'ctx.crawler_config_dict.get("retries", 3)')
content = content.replace("ctx.domain_delays", 'ctx.crawler_config_dict.get("domain_delays", {})')
content = content.replace("ctx.delay", 'ctx.crawler_config_dict.get("delay", 1.0)')
content = content.replace("ctx.jitter_ratio", 'ctx.crawler_config_dict.get("jitter_ratio", 0.2)')

# 4. Remove bad imports
content = content.replace("from crawler.manager import _get_domain_delay\n", "")

with open("crawler/manager.py", "w") as f:
    f.write(content)
