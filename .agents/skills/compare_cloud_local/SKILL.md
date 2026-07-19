---
name: compare-cloud-local
description: 自動同時觸發本地端測試與雲端 MCP 測試，並交叉比對兩者結果。若本地成功而雲端失敗，即可明確判斷為目標主機防禦策略所致。
---

# 雲端測試 MCP 與本地/雲端結果比對 (Compare Cloud and Local)

## 目的
當同一個連結在本地測試成功，但在雲端主機測試卻失敗時，這項 Skill 能夠透過一致的機制分別在本地 (link-checker-local) 與雲端 (link-checker-production) 執行相同邏輯，協助快速判斷是否為目標網站封鎖了雲端 IP 或資料中心網段。

## 觸發條件
當使用者要求「比對本地與雲端」、「測試雲端連結阻擋」、「比較 internal/external link 在 local 與 production 的差異」等指令時。

## 前置條件
- 確認使用者提供的 URL，並確認是**內部連結 (Internal)** 還是 **外部連結 (External)**。
- 若使用者未指定，預設當作外部連結處理，或詢問使用者。

## 執行步驟

### 1. 本地端測試 (Local Test)
透過 MCP Client 呼叫 `link-checker-local` 上的工具（以確保基準完全一致）：
- 若為內部連結：呼叫 `call_mcp_tool(ServerName="link-checker-local", ToolName="test_internal_url", Arguments={"url": "<URL>"})`
- 若為外部連結：呼叫 `call_mcp_tool(ServerName="link-checker-local", ToolName="test_external_url", Arguments={"url": "<URL>"})`

### 2. 雲端測試 (Cloud Test)
透過 MCP Client 呼叫 `link-checker-production` 上的工具：
- 若為內部連結：呼叫 `call_mcp_tool(ServerName="link-checker-production", ToolName="test_internal_url", Arguments={"url": "<URL>"})`
- 若為外部連結：呼叫 `call_mcp_tool(ServerName="link-checker-production", ToolName="test_external_url", Arguments={"url": "<URL>"})`

### 3. 交叉比對 (Compare)
解析兩邊回傳的 JSON 結果字串。比對核心欄位：
- `status_code`: 比較兩者的 HTTP 狀態碼。
- `error_msg`: 比較兩者的錯誤訊息。

### 4. 輸出報告 (Report)
產出對比報告。格式範例：
```markdown
# 🌐 連結探測比對報告
**測試連結**：`https://example.com`
**連結類型**：外部連結

| 環境 | 狀態碼 | 錯誤訊息 | 結論 |
|---|---|---|---|
| 🏠 本機 (Local) | 200 | 無 | 正常存取 |
| ☁️ 雲端 (Production) | 403 / 503 / None | Access Denied / Timeout | 存取失敗 |

**分析結果**：
如果本機狀態碼為 200，但雲端為 403/503 或超時，這高度暗示目標網站存在 WAF（如 Cloudflare）防禦機制，阻擋了雲端資料中心的 IP 網段。
```
