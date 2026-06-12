import sys

with open("crawler/runner.py", "r") as f:
    content = f.read()

# 1. Remove the dataclass block from the top
block = """from dataclasses import dataclass, field

@dataclass
class JobRunnerState:
    crawled_count: int = 0
    checked_links_cache: dict[str, tuple[str | None, int | None, str | None]] = field(default_factory=dict)
    target_domains_list: list[str] = field(default_factory=list)
    trusted_domains_list: list[str] = field(default_factory=list)

"""

if block in content:
    content = content.replace(block, "")

# 2. Add 'from dataclasses import dataclass, field' to the imports
import_pos = content.find("import json")
content = content[:import_pos] + "from dataclasses import dataclass, field\n" + content[import_pos:]

# 3. Add the class below logger
target = "logger = logging.getLogger(__name__)\n"
class_block = """
@dataclass
class JobRunnerState:
    \"\"\"爬蟲任務狀態追蹤資料類別。\"\"\"
    crawled_count: int = 0
    checked_links_cache: dict[str, tuple[str | None, int | None, str | None]] = field(default_factory=dict)
    target_domains_list: list[str] = field(default_factory=list)
    trusted_domains_list: list[str] = field(default_factory=list)
"""
content = content.replace(target, target + "\n" + class_block)

with open("crawler/runner.py", "w") as f:
    f.write(content)
