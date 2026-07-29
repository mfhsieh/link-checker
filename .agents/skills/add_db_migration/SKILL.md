---
name: Add DB Migration
description: 當需要修改 SQLAlchemy Models 或是資料表 Schema 時，指導 Agent 安全地進行變更並確保文件與跨資料庫的相容性。
---

# 資料庫安全異動流水線

本專案具備「Auth DB」與「Crawler DB」雙庫實體分離架構，並且同時支援開發環境的 SQLite 與正式環境的 PostgreSQL。修改資料庫 Schema 是一項高風險操作，請務必遵循以下標準流程：

## 0. 事前確認
- 在著手修改任何程式碼之前，**必須先閱讀 `doc/db_schema.md`**，充分了解現有架構與關聯，確保你的設計符合現有規範。

## 1. 修改 ORM Models (`backend/auth/models.py` 或 `crawler/models.py`)
- **跨資料庫方言 (Dialect) 相容性**：修改欄位型態、約束 (Constraints)、預設值或索引時，務必考慮 PostgreSQL 與 SQLite 的方言差異。例如避免使用 Postgres 專屬的 `JSONB` 或 `ARRAY`（除非有 fallback），並注意 SQLite 對 `ALTER TABLE` 與外鍵 (Foreign Key) 的限制。
- **屬性與預設值**：設定適當的 `default` 值、字串長度或 `nullable` 屬性。
- **效能與索引 (Index)**：若欄位會頻繁用於查詢過濾，應評估新增 `index=True`，確保雙邊資料庫的查詢效能皆能最佳化。

## 2. 同步更新資料庫文件
- 程式碼修改完成後，**必須手動打開並編輯** `doc/db_schema.md`。
- 在對應的 Markdown 表格中補上新欄位的名稱、型態、以及詳細的用途說明。
- 確保文件與程式碼永遠保持一致 (Living Documentation)。

## 3. 產生與驗證 Alembic Migration 腳本
- 本專案已正式導入 **Alembic** 管理 SQLite 與 PostgreSQL 雙庫 Schema。
- 修改 ORM Models 後，請使用虛擬環境執行以下指令產生增量版號：
  ```bash
  .venv/bin/alembic revision --autogenerate -m "描述 Schema 變更"
  ```
- 檢查產生的 `alembic/versions/xxx_描述.py` 腳本，確認 `upgrade()` 與 `downgrade()` 邏輯正確（特別注意 SQLite 的 `batch_alter_table` 處理），並確保開頭具備說明該次變更目的之 **PyDoc Docstring** 與 `# pylint: skip-file`。
- 執行升級測試與驗證：
  ```bash
  .venv/bin/alembic upgrade head
  .venv/bin/alembic check
  ```
- （選用提示）：若為既有資料庫且欄位已符合最新 Models，可使用 `.venv/bin/alembic stamp head` 進行快速版號對齊標記。
- 確認維護腳本（如 `scripts/migrate_sqlite_to_pg.py` 等）是否需要配合調整。

## 4. 驗證資料庫行為
- 執行 `Run Quality Gate` 或直接執行 `pytest test/ -v`。
- 測試環境的 SQLite DB 會在測試期間頻繁重建，如果你的 Model 定義有誤或造成語法衝突，通常會在第一時間被 `pytest` 捕捉到。
