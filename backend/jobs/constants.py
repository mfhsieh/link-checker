"""
任務相關的全域常數。
"""

import os
import subprocess

PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PID_DIR: str = os.path.join(PROJECT_ROOT, "log", "pids")
_ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}

ALLOWED_CRAWLER_CONFIG_KEYS = [
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
