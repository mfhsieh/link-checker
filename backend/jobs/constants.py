"""任務相關的全域常數。

此模組定義了外部連結檢查任務所需的全域路徑、子程序對應表以及合法的爬蟲配置項常數。
"""

import os
import subprocess

PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PID_DIR: str = os.path.join(PROJECT_ROOT, "log", "pids")
_ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}

ALLOWED_CRAWLER_CONFIG_KEYS: list[str] = [
    "max_depth",
    "max_pages",
    "delay",
    "timeout",
    "connect_timeout",
    "external_check_timeout",
    "retries",
    "proxy_url",
    "user_agent",
    "ignore_extensions",
    "ignore_regexes",
    "ssl_exempt_domains",
    "social_domains",
    "domain_delays",
]

SSE_POLL_INTERVAL_SEC: int = 10
