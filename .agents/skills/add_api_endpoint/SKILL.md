---
name: Add API Endpoint
description: 當需要新增或修改 FastAPI 路由時，指導 Agent 遵守專案的標準化流水線，包含 Schema 定義、Router 實作、測試與文件更新。
---

# 新增 API 端點的標準化流水線

本專案的前後端採用嚴格的 API 契約 (API Contract) 進行溝通。當你需要為系統新增或修改一支 API 時，必須嚴格遵守以下流程：

## 1. 定義 Schema
- 在動手寫業務邏輯前，必須先在 Schema 檔案（如 `backend/schemas.py` 或 `backend/auth/schemas.py`）中定義 Request 與 Response 的 Pydantic Model。
- 確保 Model 有明確的 Type Hinting，並適時加上 `Field` 描述。

## 2. 實作業務邏輯與路由
- 遵循現有的 Controller / Service 分層原則。
- 在 FastAPI 路由裝飾器 (Router Decorator) 中，必須明確指定 `response_model`。
- 若該 API 需要身分驗證，請確保掛上適當的 `Depends` 依賴。

## 3. 撰寫單元測試
- 新增 API 後，**絕對不允許**在沒有測試的情況下提交。
- 測試必須覆蓋「正常路徑 (Happy Path)」與「預期外的邊界錯誤 (Edge Cases)」。
- 確保測試檔案使用了 `test/conftest.py` 中正確的 Fixtures，不要破壞模組間的隔離。

## 4. 自動更新 API 文件 (Living Documentation)
- **這是最重要的一步**。實作完成後，務必使用專案內的自動化腳本更新文件。
- 請執行：`.venv/bin/python scripts/gen_api_doc.py`（或透過 bash 啟動虛擬環境執行）。
- 執行後，檢查 `doc/api_spec.md` 與 `doc/api_routes.md` 是否已正確反映你的修改。
