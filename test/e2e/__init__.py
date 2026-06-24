"""E2E 測試模組套件。

此模組包含網站連結檢查系統的端到端 (E2E) 測試案例，包含以下模組：
- conftest: 提供 E2E 測試專用的 Playwright 與環境 fixtures。
- test_admin: 測試後台管理介面與功能的 E2E 案例。
- test_app: 測試主要應用程式流程 (如建立任務、查看報表) 的 E2E 案例。
- test_auth: 測試登入與註冊流程的 E2E 案例。
- test_duplicate: 測試防呆與重複操作行為的 E2E 案例。
"""
