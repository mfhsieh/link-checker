import re

with open("backend/config.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
skip_init = False
for i, line in enumerate(lines):
    if line.strip() == "# pylint: disable=invalid-name":
        continue
    if line.strip() == 'def __init__(self) -> None:':
        skip_init = True
        continue
    if skip_init and line.strip() == '"""初始化應用程式設定，並從環境變數載入數值。"""':
        skip_init = False
        continue
        
    if "self." in line and not skip_init:
        # replace `        self.X` with `    X`
        # which means dedent by 4 spaces and remove `self.`
        match = re.match(r"^(\s{8})self\.(.*)$", line)
        if match:
            new_lines.append("    " + match.group(2) + "\n")
            continue
    
    # Also dedent comments that are inside the init
    if line.startswith("        #"):
        new_lines.append("    " + line.lstrip(" "))
        continue

    new_lines.append(line)

# Add pylint: disable=too-few-public-methods to class docstring or top of file.
# We'll put it at the top of file after the module docstring.
for i, line in enumerate(new_lines):
    if "import os" in line:
        new_lines.insert(i, "# pylint: disable=too-few-public-methods\n\n")
        break

with open("backend/config.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)

