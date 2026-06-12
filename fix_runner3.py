import sys

with open("crawler/runner.py", "r") as f:
    lines = f.readlines()

out = []
for line in lines:
    if line.strip() == "from dataclasses import dataclass, field":
        continue
    out.append(line)

content = "".join(out)
import_pos = content.find("import json")
content = content[:import_pos] + "from dataclasses import dataclass, field\n" + content[import_pos:]

with open("crawler/runner.py", "w") as f:
    f.write(content)
