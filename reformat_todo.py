import re

with open("doc/todo.md", "r", encoding="utf-8") as f:
    lines = f.readlines()

def extract_section(keyword):
    start_idx = -1
    for i, line in enumerate(lines):
        if line.startswith(f"#### {keyword}. ") or (line.startswith("#### ") and f" {keyword}. " in line):
            start_idx = i
            break
    if start_idx == -1: return []
    
    end_idx = start_idx + 1
    while end_idx < len(lines):
        if lines[end_idx].startswith("#### ") or lines[end_idx].startswith("## ") or lines[end_idx].startswith("---"):
            break
        end_idx += 1
        
    extracted = lines[start_idx:end_idx]
    del lines[start_idx:end_idx]
    return extracted

# 1. Extract 8 and 9
item_8 = extract_section(8)
item_9 = extract_section(9)

# Update their status to Resolved
for i in range(len(item_8)):
    if "* **狀態**：" in item_8[i]:
        item_8[i] = "* **狀態**：**已解決（Resolved）**。\n"

for i in range(len(item_9)):
    if "* **狀態**：" in item_9[i]:
        item_9[i] = "* **狀態**：**已解決（Resolved）** - 已實作 AuditLogService 並於各 API 點觸發對應事件。\n"
    if item_9[i].startswith("#### "):
        item_9[i] = item_9[i].replace("#### 9. ", "#### 9. [已完成] ")

# 2. Extract Dropped items (they are currently 23, 24, 25, 26)
item_23 = extract_section(23)
item_24 = extract_section(24)
item_25 = extract_section(25)
item_26 = extract_section(26)

# Update their status
dropped_items = [item_23, item_24, item_25, item_26]
reasons = [
    "API 速率限制通常交由反向代理層（如 Nginx、Cloudflare）處理，在應用層實作會增加不必要的效能開銷與維護成本，對於內部使用的工具而言屬於過度設計。",
    "引入 Celery 或 Redis 等外部依賴會大幅增加專案的部署難度與架構複雜度。目前的 `ThreadPoolExecutor` 已經足夠應付單機環境下的效能需求，維持輕量級部署更符合本專案的定位。",
    "CLI 主要用於自動化或 CI 環境，使用者通常會將完整結果輸出為 JSON 後再利用 `jq` 進行處理。將複雜的過濾邏輯重複實作在 CLI 參數中不但效益低，也會增加開發負擔。Web 介面已經提供完整的篩選功能。",
    "本專案並未牽涉到複雜的子網域架構。目前的 `SameSite=Strict` Cookie 加上標準的 Double Submit Cookie 模式已經足以防禦絕大部分的 CSRF 攻擊。HMAC 綁定實作複雜度高但帶來的實際安全效益邊際遞減。"
]

for item, reason in zip(dropped_items, reasons):
    for i in range(len(item)):
        if "* **狀態**：" in item[i]:
            item[i] = f"* **狀態**：**已擱置（Dropped）** - 原因：{reason}\n"

# 3. Put them back in the correct sections
# Find "## 已解決 / 已完成"
resolved_idx = -1
for i, line in enumerate(lines):
    if "## 已解決 / 已完成" in line:
        resolved_idx = i
        break

if resolved_idx != -1:
    # insert after the subtext
    insert_idx = resolved_idx + 2
    if insert_idx < len(lines) and "歷史完成項目" in lines[insert_idx]:
        insert_idx += 1
    if insert_idx < len(lines) and lines[insert_idx].strip() == "":
        insert_idx += 1
    
    # Insert 8 and 9
    lines = lines[:insert_idx] + item_8 + item_9 + lines[insert_idx:]

# Find "## 永久擱置 / 已移除"
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
        
    lines = lines[:insert_idx] + item_23 + item_24 + item_25 + item_26 + lines[insert_idx:]

with open("doc/todo.md", "w", encoding="utf-8") as f:
    f.writelines(lines)
