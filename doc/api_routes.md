# API 路由清單 (API Route Reference)

本文件列出前台與後台所需的核心 REST API 端點，供前後端開發對齊界面邊界。所有端點均以 `/api/` 為前綴，回應格式為 JSON。

## 1. 身分驗證 API

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| `POST` | `/api/auth/login` | 一般登入（email + password）或首次登入（email + uuid） | 公開 |
| `POST` | `/api/auth/set-password` | 首次登入後強制設定密碼 | 首次登入 Session |
| `POST` | `/api/auth/logout` | 登出，清除 Session Token | 已登入 |
| `GET` | `/api/auth/me` | 取得當前登入使用者資訊（email、role、status） | 已登入 |
| `PATCH` | `/api/auth/password` | 修改密碼（需提供現有密碼） | 已登入 |

## 2. 任務管理 API（前台）

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| `GET` | `/api/jobs/default-config` | 取得任務預設之全域配置與上下限參數 | 已登入 |
| `GET` | `/api/jobs` | 列出當前使用者的所有任務 | 已登入 |
| `POST` | `/api/jobs` | 建立新任務 | 已登入 |
| `GET` | `/api/jobs/{job_id}` | 取得任務詳情（含進度） | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/start` | 啟動任務 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/pause` | 暫停任務 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/resume` | 恢復任務 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/transfer` | 將任務移交給其他使用者 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/reset` | 重置任務 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/retry-failed` | 局部重試任務的失敗項目 | 已登入（僅限自身任務） |
| `DELETE` | `/api/jobs/{job_id}` | 刪除任務及所有結果 | 已登入（僅限自身任務） |

## 3. 結果查閱 API（前台）

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| `GET` | `/api/jobs/{job_id}/results` | 列出外連結果（支援篩選、排除網域、分頁） | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/results/summary` | 取得任務統計摘要 | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/diff?compare_with={id}` | 任務結果差異比對 (Diff Engine) | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/results/export` | 匯出結果（CSV / JSON，支援篩選、排除網域） | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/export/full` | 匯出完整報表大禮包 (ZIP 壓縮檔) | 已登入（僅限自身任務） |

## 4. 後台管理 API

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| `GET` | `/api/admin/users` | 列出所有使用者帳號 | Admin |
| `POST` | `/api/admin/users` | 新增使用者並寄送邀請 | Admin |
| `PATCH` | `/api/admin/users/{user_id}` | 修改帳號狀態或角色 | Admin |
| `DELETE` | `/api/admin/users/{user_id}` | 刪除帳號及所有關聯資料 | Admin |
| `POST` | `/api/admin/users/{user_id}/resend-invite` | 重新寄送邀請 | Admin |
| `GET` | `/api/admin/jobs` | 列出所有使用者的任務 | Admin |
| `POST` | `/api/admin/jobs/{job_id}/takeover` | 強制接管（解鎖卡死任務） | Admin |
| `DELETE` | `/api/admin/jobs/{job_id}` | 強制刪除任意任務 | Admin |
| `GET` | `/api/admin/config` | 取得全域配置 | Admin |
| `PATCH` | `/api/admin/config` | 修改全域配置 | Admin |
| `GET` | `/api/admin/smtp` | 取得 SMTP 配置狀態（唯讀，從環境變數讀取，密碼遮罩） | Admin |
| `POST` | `/api/admin/smtp/test` | 寄送測試郵件 | Admin |
| `GET` | `/api/admin/logs` | 查閱系統操作日誌（支援時間範圍、事件類型與使用者篩選，支援分頁） | Admin |

## 5. 系統與其他 API

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| `GET` | `/api/health` | 服務健康檢查端點（供 CI/CD 或 Load Balancer 使用） | 公開 |
