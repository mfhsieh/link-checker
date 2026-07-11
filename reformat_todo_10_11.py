import re

with open("doc/todo.md", "r", encoding="utf-8") as f:
    lines = f.readlines()


def extract_section(keyword):
    start_idx = -1
    for i, line in enumerate(lines):
        if line.startswith(f"#### {keyword}. ") or (line.startswith("#### ") and f" {keyword}. " in line):
            start_idx = i
            break
    if start_idx == -1:
        return []

    end_idx = start_idx + 1
    while end_idx < len(lines):
        if lines[end_idx].startswith("#### ") or lines[end_idx].startswith("## ") or lines[end_idx].startswith("---"):
            break
        end_idx += 1

    extracted = lines[start_idx:end_idx]
    del lines[start_idx:end_idx]
    return extracted


item_10 = extract_section(10)
item_11 = extract_section(11)

for i in range(len(item_10)):
    if "* **狀態**：" in item_10[i]:
        item_10[i] = (
            "* **狀態**：**已擱置（Dropped）** - 原因：目前快取僅針對靜態的歷史任務診斷結果，並不會因為全域設定或使用者權限異動而導致資料不同步，因此無需實作複雜的快取更新事件。\n"
        )

for i in range(len(item_11)):
    if "* **狀態**：" in item_11[i]:
        item_11[i] = (
            "* **狀態**：**已擱置（Dropped）** - 原因：系統目前主要需求為「針對單一任務的診斷報告」，並無跨任務的大型數據統計看板需求。直接修改核心或增加獨立報表服務屬過度設計。\n"
        )

dropped_idx = -1
for i, line in enumerate(lines):
    if "## 永久擱置 / 已移除" in line:
        dropped_idx = i
        break

if dropped_idx != -1:
    insert_idx = dropped_idx + 2
    if insert_idx < len(lines) and "以下項目經評估" in lines[insert_idx]:
        insert_idx += 1
    if insert_idx < len(lines) and lines[insert_idx].strip() == "":
        insert_idx += 1

    lines = lines[:insert_idx] + item_10 + item_11 + lines[insert_idx:]

with open("doc/todo.md", "w", encoding="utf-8") as f:
    f.writelines(lines)
