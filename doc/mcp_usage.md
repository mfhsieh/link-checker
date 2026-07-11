# MCP Server 使用指南

本系統提供一組基於 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 規格的本地獨立伺服器，專門供開發者與 AI 助理（如 Claude Desktop 或 Cursor）使用，以方便地直接查閱遠端 Production 或 Staging 環境中的爬蟲任務執行狀態。

## 架構說明

MCP Server 採用 **Standalone Stdio Transport** 架構：
- **獨立運行**：透過 `scripts/mcp_server.py` 直接啟動。
- **直接讀取**：程式會透過現有設定 (`config.py` 與 `deps.py`) 直接連接 `crawler.db`。
- **標準通訊**：採用 `stdio`（標準輸出入）進行 JSON-RPC 通訊，這代表你可以直接透過 SSH 在遠端主機上執行它，並將結果回傳至本地。

## 開發者本地 (Client) 設定教學

假設您的專案佈署在遠端伺服器上（如 `myserver.com`），且您的專案路徑為 `/opt/link-checker`。
若要在本地端的開發工具中連接此伺服器，請將以下設定加入至該工具的 MCP 設定檔中（例如 Claude Desktop 的 `claude_desktop_config.json`，或是 Antigravity IDE (Gemini) 的 `~/.gemini/config/mcp_config.json`）。

有兩種常見的 ssh 連線設定方式：

**方法 1：使用 `.ssh/config` (推薦)**
在您的電腦上編輯 `~/.ssh/config`，事先定義好連線資訊：
```text
Host myserver-prod
    HostName myserver.com
    User user
    IdentityFile ~/.ssh/id_rsa_production
```
然後在 MCP 設定檔中，將 `ssh` 目標設定為 `myserver-prod` 即可，這樣配置會更加整潔：

```json
{
  "mcpServers": {
    "link-checker-production": {
      "command": "ssh",
      "args": [
        "myserver-prod",
        "cd /opt/link-checker && .venv/bin/python scripts/mcp_server.py"
      ]
    }
  }
}
```

**方法 2：直接在設定檔加入 `-i` 參數**
將您的私鑰絕對路徑加到 `args` 的最前面：
```json
{
  "mcpServers": {
    "link-checker-production": {
      "command": "ssh",
      "args": [
        "-i",
        "/Users/yourname/.ssh/id_rsa_production",
        "user@myserver.com",
        "cd /opt/link-checker && .venv/bin/python scripts/mcp_server.py"
      ]
    }
  }
}
```

## 提供的 Tools

MCP Server 啟動後，將向您的 AI 助理註冊以下 Tools：

1. **`list_active_jobs`**
   - **功能**：列出目前系統中所有狀態為 `running` 或 `pending` 的任務。
   - **回傳**：包含任務 ID (`job_id`)、狀態、起始網址與建立時間的 JSON 列表。

2. **`get_job_progress`**
   - **參數**：`job_id` (字串)
   - **功能**：查詢該任務中各項 `status_category`（例如：ok, pending, not_found, blocked）的統計數量，並計算整體進度百分比。

3. **`get_job_errors`**
   - **參數**：`job_id` (字串)、`limit` (數字，預設 10)
   - **功能**：針對特定任務，抓取最新發生的錯誤連結資訊（包含錯誤訊息與狀態碼），以協助 AI 快速診斷失敗原因。

## 擴充與維護

如果您需要擴充新的 MCP Tool 來查詢其他報表（例如 Auth 系統的使用者統計），請直接編輯 `scripts/mcp_server.py`：
1. 引用相關的 ORM Model。
2. 使用 `@mcp.tool()` 裝飾器定義新的 Python Function。
3. 函數必須加上明確的 Type Hinting 與 Docstring（MCP 會自動將 Docstring 轉換為 Tool Description 給 AI 讀取）。
