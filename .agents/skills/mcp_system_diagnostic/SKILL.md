---
name: mcp_system_diagnostic
description: 自動整合 MCP 工具（get_jobs_status + get_disk_usage），提供一鍵式系統健康度盤點，自動巡檢生產環境與本地端的任務執行狀況、佇列堆積量與磁碟佔用告警。
---

# MCP 系統健康度診斷技能 (MCP System Diagnostic)

## 目的
提供一鍵式系統健康度檢測，讓 Agent 能夠同時對本地 (link-checker-local) 與雲端 (link-checker-production) 執行任務進度盤點、異常任務掃描以及磁碟容量風險檢測。

## 觸發時機
當使用者詢問「檢查系統健康度」、「檢查 MCP 服務狀態」、「生產環境/本地任務進度與磁碟空間」等指令時。

## 執行步驟

### 1. 查詢任務執行狀態 (Job Status Diagnostic)
透過 MCP Client 分別查詢本地與雲端環境：
- 本地端：`call_mcp_tool(ServerName="link-checker-local", ToolName="get_jobs_status", Arguments={})`
- 雲端生產端：`call_mcp_tool(ServerName="link-checker-production", ToolName="get_jobs_status", Arguments={})`

### 2. 檢查實體磁碟與日誌容量 (Disk & Storage Usage)
- 本地端：`call_mcp_tool(ServerName="link-checker-local", ToolName="get_disk_usage", Arguments={})`
- 雲端生產端：`call_mcp_tool(ServerName="link-checker-production", ToolName="get_disk_usage", Arguments={})`

### 3. 彙整健康度診斷報告
解析兩端回傳之 JSON 數據，匯出包含「任務狀態摘要」、「異常任務警示」與「磁碟容量警告」之結構化報告。
