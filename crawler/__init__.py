"""
爬蟲核心套件。

此套件提供外部連結檢查爬蟲 (Link Checker Crawler) 的核心元件，包含以下模組：

- config_utils: 提供爬蟲設定檔解析、驗證與環境變數管理功能。
- core: 實作 HTTP 請求發送、內容解析與連結萃取的核心爬蟲引擎。
- manager: 負責管理爬蟲任務狀態與資料庫操作的管理器。
- models: 定義爬蟲專用資料庫的模型 (Job, CrawlQueue, ExternalLink 等)。
- profiles: 管理不同的爬蟲參數設定檔。
- runner: 封裝單一爬蟲任務的執行邏輯。
- utils: 提供 URL 解析、IP 查詢與狀態判定等通用工具。

此 ``__init__.py`` 不直接匯出任何公開符號，使用者請直接引用各子模組。
"""
