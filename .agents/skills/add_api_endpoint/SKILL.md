---
name: Add API Endpoint
description: 當需要新增或修改 FastAPI 路由時，指導 Agent 遵守專案的標準化流水線，包含 Schema 定義、Router 實作、測試與文件更新。
---

# 新增 API 端點的標準化流水線

本專案的前後端採用嚴格的 API 契約 (API Contract) 進行溝通。當你需要為系統新增或修改一支 API 時，必須嚴格遵守以下流程：

## 1. 定義 Schema
- 在動手寫業務邏輯前，必須先定義 Request 與 Response 的 Pydantic Model。請依照現有的模組結構放置檔案：
  - **Jobs 模組**：定義於 `backend/jobs/schemas.py`
  - **Auth 或 Admin 等模組**：目前直接定義於對應的 `router.py`（如 `backend/auth/router.py` 或 `backend/admin/router.py`）內。
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
- 執行後，檢查 `doc/api_spec.md` 與 `doc/api_routes.md` 是否已正確反映修改。

## 5. 執行專案品質閘門 (Quality Gate)
- 實作與文件更新皆完成後，**必須**觸發「Run Quality Gate」技能或執行 `.agents/skills/run_quality_gate/scripts/check.sh`。
- 確保程式碼通過 Ruff 排版、Pylint 靜態分析、Mypy 型別檢查與 Pytest 單元測試。若有任何錯誤，請自動進行修復（在取得使用者同意後修改程式碼）並重新驗證，直至所有檢查皆順利通過。
