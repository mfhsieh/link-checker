# Python 執行與環境規範 (Virtual Environment Rule)

- 本專案已在本地建立虛擬環境 `.venv`。
- 當你需要使用終端機執行任何 `python`, `pytest`, `pip` 或專案內的腳本（例如 `cli.py`）時，**必須嚴格遵守以下兩種執行方式之一**：
  1. 使用虛擬環境直譯器的明確路徑，例如：`.venv/bin/python scripts/gen_api_doc.py`。
  2. 在同一行指令中先啟動虛擬環境，例如：`source .venv/bin/activate && python ...`。
- **嚴格禁止**：在未啟動虛擬環境或未指定虛擬環境路徑的情況下，直接呼叫全域的 `python` 指令。

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

---

# 文件同步更新原則 (Documentation Sync Rule)

為了確保 `doc/` 目錄下的文件永遠與程式碼保持一致（Living Documentation），當你完成特定模組的開發或修改後，**必須主動執行對應的文件更新操作**：
1. **API 異動**：如果你新增、修改或刪除了任何 Backend API 的路由 (Router) 或資料綱要 (Schema)，在回報完成前，**必須使用虛擬環境執行** `python scripts/gen_api_doc.py`，讓系統自動重新產生最新的 API 文件。
2. **資料庫異動**：如果你修改了 SQLAlchemy Model、資料表結構，或是新增了欄位，**必須手動編輯更新** `doc/db_schema.md` 以準確反映最新的欄位、型態與用途。
3. **任務狀態異動**：如果你協助解決了 `doc/todo.md` 中的某個問題，**必須主動編輯該檔案**，將該項目的狀態改為「已解決 (Resolved)」或進行相應的狀態更新。
4. **架構與流程異動**：如果你重構了核心模組或改變了系統資料流，**必須主動評估並更新** `doc/architecture.md` 或 `doc/crawler_workflow.md`。

這是強制規定，請勿留下「程式碼已改，但文件未更新」的技術債。
