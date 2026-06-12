import sys
import re

with open("crawler/manager.py", "r") as f:
    content = f.read()

# Fix docstrings
content = content.replace("    def target_domains_list(self) -> list[str]:\n", '    def target_domains_list(self) -> list[str]:\n        """取得目標網域清單。"""\n')
content = content.replace("    def trusted_domains_list(self) -> list[str]:\n", '    def trusted_domains_list(self) -> list[str]:\n        """取得信任網域清單。"""\n')

# Remove unused variables
content = re.sub(r'        target_domains_list: list\[str\] = \(\n            job\.target_domains\.split\(","\)\n            if job\.target_domains\n            else \[\]\n        \)\n', '', content)
content = re.sub(r'        trusted_domains_list: list\[str\] = \(\n            job\.trusted_domains\.split\(","\)\n            if job\.trusted_domains\n            else \[\]\n        \)\n', '', content)

# Try one-liner version if they were formatted differently
content = re.sub(r'        target_domains_list: list\[str\] = job\.target_domains\.split\(","\) if job\.target_domains else \[\]\n', '', content)
content = re.sub(r'        trusted_domains_list: list\[str\] = job\.trusted_domains\.split\(","\) if job\.trusted_domains else \[\]\n', '', content)


with open("crawler/manager.py", "w") as f:
    f.write(content)
