import sys

with open("crawler/notifier.py", "r") as f:
    content = f.read()

# Remove the block from the top
block = """from dataclasses import dataclass

@dataclass
class JobStats:
    \"\"\"外部連結統計資訊。\"\"\"

    total: int
    healthy: int
    broken: int
    dead: int

"""
if block in content:
    content = content.replace(block, "")

# Find where to put it
target = "logger: logging.Logger = logging.getLogger(__name__)\n"
content = content.replace(target, target + "\n" + block)

with open("crawler/notifier.py", "w") as f:
    f.write(content)
