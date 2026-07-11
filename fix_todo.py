import re

with open("doc/todo.md", "r", encoding="utf-8") as f:
    content = f.read()

# Let's fix the merged line 194
content = content.replace("邊際遞減。#### 9. ", "邊際遞減。\n\n#### 9. ")

# Also fix Item 9's status
content = content.replace(
    "#### 9. 引入管理員操作稽核日誌事件 (Audit Logging via Events)",
    "#### 9. [已完成] 引入管理員操作稽核日誌事件 (Audit Logging via Events)",
)
content = content.replace(
    "* **狀態**：**待排程（Pending）**。",
    "* **狀態**：**已解決（Resolved）** - 已實作 AuditLogService 並於各 API 點觸發對應事件。",
)

# We want to move Item 9 under "## 已解決 / 已完成 (Resolved / Completed)"
# Let's first extract it.
pattern_9 = r"#### 9\. \[已完成\].*?實作 AuditLogService 並於各 API 點觸發對應事件。\n"
match_9 = re.search(pattern_9, content, re.DOTALL)

if match_9:
    item_9_text = match_9.group(0)
    # Remove it from its current location
    content = content.replace(item_9_text, "")

    # Find "## 已解決 / 已完成"
    resolved_header = "## 已解決 / 已完成 (Resolved / Completed)\n\n*(本區塊的歷史完成項目已全數歸檔並整併至 doc/requirements.md 作為系統規範)*\n"
    if resolved_header in content:
        content = content.replace(resolved_header, resolved_header + "\n" + item_9_text)
    else:
        # Just append it if we can't find the header exactly
        resolved_header2 = "## 已解決 / 已完成"
        idx = content.find(resolved_header2)
        if idx != -1:
            idx_end = content.find("\n", idx)
            idx_end2 = content.find("\n", idx_end + 1)  # skip the italic text
            idx_end3 = content.find("\n", idx_end2 + 1)
            content = content[: idx_end3 + 1] + "\n" + item_9_text + content[idx_end3 + 1 :]

# Next, the TOC might be messed up. Line 199 has `- [永久擱置 / 已移除` instead of being at the top.
# Let's find if it's placed incorrectly at the bottom of the file.
toc_line = "- [永久擱置 / 已移除 (Dropped / Removed)](#永久擱置--已移除-dropped--removed)\n"
if content.endswith(toc_line) or content.endswith(toc_line + "\n"):
    content = content.replace(toc_line, "")

# We must ensure the TOC has the dropped link at the right place, i.e., after the Resolved link.
toc_resolved = "- [已解決 / 已完成 (Resolved / Completed)](#已解決--已完成-resolved--completed)\n"
if toc_resolved in content and toc_line not in content:
    content = content.replace(toc_resolved, toc_resolved + toc_line)

with open("doc/todo.md", "w", encoding="utf-8") as f:
    f.write(content)
