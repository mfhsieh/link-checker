import sys
import re

with open("crawler/notifier.py", "r") as f:
    content = f.read()

# 1. Add dataclass import and JobStats class
import_pos = content.find("import logging")
dataclass_code = "from dataclasses import dataclass\n\n@dataclass\nclass JobStats:\n    \"\"\"外部連結統計資訊。\"\"\"\n    total: int\n    healthy: int\n    broken: int\n    dead: int\n\n"

content = content[:import_pos] + dataclass_code + content[import_pos:]

# 2. Update _build_and_send_email signature
sig_pattern = re.compile(r"def _build_and_send_email\(\n    to_email: str,\n    job: Job,\n    status: str,\n    total_count: int,\n    healthy_count: int,\n    broken_count: int,\n    dead_count: int,\n\) -> None:")
sig_replacement = """def _build_and_send_email(
    to_email: str,
    job: Job,
    status: str,
    stats: JobStats,
) -> None:"""
content = sig_pattern.sub(sig_replacement, content)

# 3. Update variables inside _build_and_send_email
content = content.replace("{total_count}", "{stats.total}")
content = content.replace("{healthy_count}", "{stats.healthy}")
content = content.replace("{broken_count}", "{stats.broken}")
content = content.replace("{dead_count}", "{stats.dead}")

# 4. Update the call to _build_and_send_email
call_pattern = re.compile(r"        _build_and_send_email\(\n            to_email, job, status, total_count, healthy_count, broken_count, dead_count\n        \)")
call_replacement = """        stats = JobStats(
            total=total_count, healthy=healthy_count, broken=broken_count, dead=dead_count
        )
        _build_and_send_email(to_email, job, status, stats)"""
content = call_pattern.sub(call_replacement, content)


with open("crawler/notifier.py", "w") as f:
    f.write(content)
