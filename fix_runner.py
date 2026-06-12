import re

with open("crawler/runner.py", "r") as f:
    content = f.read()

# 1. Add JobRunnerState
import_pos = content.find("import json")
state_code = "from dataclasses import dataclass, field\n\n@dataclass\nclass JobRunnerState:\n    crawled_count: int = 0\n    checked_links_cache: dict[str, tuple[str | None, int | None, str | None]] = field(default_factory=dict)\n    target_domains_list: list[str] = field(default_factory=list)\n    trusted_domains_list: list[str] = field(default_factory=list)\n\n"
content = content[:import_pos] + state_code + content[import_pos:]

# 2. Update __init__
init_pattern = re.compile(r"        self\.target_domains_list.*?        self\.executor: ThreadPoolExecutor \| None = None", re.DOTALL)
init_replacement = """        self.crawler_config_dict: dict[str, object] = {}
        self.state = JobRunnerState()
        self.executor: ThreadPoolExecutor | None = None"""
content = init_pattern.sub(init_replacement, content)

# 3. Replace initialization in _initialize
init2_pattern = re.compile(r"        self\.target_domains_list = .*?        self\.crawled_count = \(\n", re.DOTALL)

init2_replacement = """        self.state.target_domains_list = job.target_domains.split(",") if job.target_domains else []
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

        self.state.crawled_count = (\n"""

content = init2_pattern.sub(init2_replacement, content)

# 4. Replace other occurrences
replacements = {
    "self.crawled_count": "self.state.crawled_count",
    "self.checked_links_cache": "self.state.checked_links_cache",
    "self.target_domains_list": "self.state.target_domains_list",
    "self.trusted_domains_list": "self.state.trusted_domains_list",
    "self.max_depth": "self.crawler_config_dict.get('max_depth', None)",
    "self.max_pages": "self.crawler_config_dict.get('max_pages', None)",
    "self.retries": "self.crawler_config_dict.get('retries', 3)",
    "self.delay": "self.crawler_config_dict.get('delay', 1.0)",
    "self.domain_delays": "self.crawler_config_dict.get('domain_delays', {})",
    "self.jitter_ratio": "self.crawler_config_dict.get('jitter_ratio', 0.2)",
}

for old, new in replacements.items():
    content = content.replace(old, new)

# Also remove the pylint disable at the top
content = content.replace("# pylint: disable=too-many-instance-attributes\n", "")

with open("crawler/runner.py", "w") as f:
    f.write(content)
