---
trigger: always_on
---

# 專案文件查閱優先原則 (Documentation First Rule)

- 本專案具有非常完整的規格與規劃文件，統一存放在 `doc/` 目錄下。
- 當使用者要求進行「新功能開發」、「架構設計」、「重構」或「除錯」時，**在動手寫程式碼或提出解決方案之前，你必須主動使用工具查看以下文件**：
  1. `doc/requirements.md` (全域核心：確認系統架構限制、效能要求與商業邏輯)
  2. `doc/architecture.md` (架構設計：了解系統整體運作與模組劃分)
  3. `doc/todo.md` (任務追蹤：確認是否有相關的待辦規劃、已知技術債或實作細節)
  4. `doc/db_schema.md` (資料庫層：進行 ORM 操作或修改 Table 前必須查閱)
  5. `doc/api_spec.md` & `doc/api_routes.md` (API 層：串接、新增或修改端點前必須查閱)
  6. `doc/crawler_workflow.md` (領域核心：處理爬蟲降級、排程與連線邏輯前必看)
  7. `doc/python_coding_style.md` & `doc/js_coding_style.md` (風格指南：確保產出的程式碼符合專案規範)
- **嚴格禁止**：僅憑自己的猜測或通用知識就擅自動手修改系統核心邏輯，確保所有修改皆符合專案規格。