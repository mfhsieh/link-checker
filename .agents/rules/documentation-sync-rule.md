---
trigger: always_on
---

# 文件同步更新原則 (Documentation Sync Rule)

- 為了確保 `doc/` 目錄下的文件永遠與程式碼保持一致（Living Documentation），當你完成特定模組的開發或修改後，**必須主動執行對應的文件更新操作**：
  1. **API 異動**：如果你新增、修改或刪除了任何 Backend API 的路由 (Router) 或資料綱要 (Schema)，在回報完成前，**必須使用虛擬環境執行** `python scripts/gen_api_doc.py`，讓系統自動重新產生最新的 API 文件。
  2. **資料庫異動**：如果你修改了 SQLAlchemy Model、資料表結構，或是新增了欄位，**必須手動編輯更新** `doc/db_schema.md` 以準確反映最新的欄位、型態與用途。
  3. **任務狀態異動**：如果你協助解決了 `doc/todo.md` 中的某個問題，**必須主動編輯該檔案**，將該項目的狀態改為「已解決 (Resolved)」或進行相應的狀態更新。
  4. **架構與流程異動**：如果你重構了核心模組或改變了系統資料流，**必須主動評估並更新** `doc/architecture.md` 或 `doc/crawler_workflow.md`。
- **強制規定**：請勿留下「程式碼已改，但文件未更新」的技術債。