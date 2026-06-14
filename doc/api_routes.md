# API 路由清單 (API Route Reference)

本文件由系統自動從 OpenAPI Schema 萃取產生，列出前台與後台所需的核心 REST API 端點。所有端點均以 `/api/` 為前綴，回應格式為 JSON（除匯出路由外）。

## 1. 身分驗證 API (`/api/auth`)

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| `POST` | `/api/auth/login` | 使用者登入。 | 公開 |
| `POST` | `/api/auth/set-password` | 首次登入後的強制密碼設定。 | 首次登入 Session |
| `POST` | `/api/auth/logout` | 登出並清除 Session Token。 | 已登入 |
| `GET` | `/api/auth/me` | 取得當前已登入使用者的基本資訊。 | 已登入 |
| `PATCH` | `/api/auth/password` | 已登入使用者修改密碼（需提供現有密碼進行驗證）。 | 已登入 |

## 2. 任務管理 API (`/api/jobs`)

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| `GET` | `/api/jobs/default-config` | 取得任務預設的全域配置，供前端建立任務時填入預設值與限制。 | 已登入 |
| `GET` | `/api/jobs` | 列出當前使用者的所有任務。 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs` | 建立新的爬蟲任務。 | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}` | 取得任務詳情（含進度）。 | 已登入（僅限自身任務） |
| `DELETE` | `/api/jobs/{job_id}` | 刪除任務及所有相關資料。 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/start` | 啟動任務（spawn 爬蟲子程序）。 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/pause` | 暫停任務（協同暫停，更新 DB 狀態）。 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/resume` | 恢復已暫停的任務（只允許 paused 狀態）。 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/reset` | 重置任務（清除結果並回到 pending 狀態）。 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/retry-failed` | 局部重試任務中的失敗項目。 | 已登入（僅限自身任務） |
| `POST` | `/api/jobs/{job_id}/transfer` | 將任務移交給其他使用者。 | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/results` | 外連結果列表（支援篩選、搜尋、去重聚合與分頁）。 | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/results/summary` | 取得任務結果統計摘要。 | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/diff` | 比對兩個任務的外連結果差異 (支援排除網域)。 | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/internal-results/summary` | 取得任務內部網頁爬取失敗的統計摘要。 | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/internal-results` | 取得內部網頁爬取失敗的紀錄列表（支援分頁）。 | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/results/export` | 匯出外連結果（CSV 或 JSON 格式下載）。 | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/internal-results/export` | 匯出內部失效結果（CSV 或 JSON 格式下載）。 | 已登入（僅限自身任務） |
| `GET` | `/api/jobs/{job_id}/export/full` | 匯出完整報表 (ZIP 壓縮檔)，內含爬取紀錄與外連清單。 | 已登入（僅限自身任務） |

## 3. 系統管理台 API (`/api/admin`)

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| `GET` | `/api/admin/users` | 列出所有使用者帳號。 | 管理員 |
| `POST` | `/api/admin/users` | 新增使用者並寄送邀請郵件。 | 管理員 |
| `PATCH` | `/api/admin/users/{user_id}` | 修改帳號狀態或角色。帳號停用時自動清除所有 Session。 | 管理員 |
| `DELETE` | `/api/admin/users/{user_id}` | 刪除帳號及所有關聯資料（含 Crawler DB 中的任務）。 | 管理員 |
| `POST` | `/api/admin/users/{user_id}/resend-invite` | 重新寄送邀請郵件（重置邀請 token）。 | 管理員 |
| `GET` | `/api/admin/jobs` | 列出所有使用者的任務（Admin 全視圖）。 | 管理員 |
| `POST` | `/api/admin/jobs/{job_id}/takeover` | 強制接管卡死任務（重置 running 狀態為 paused）。 | 管理員 |
| `DELETE` | `/api/admin/jobs/{job_id}` | 強制刪除任意任務（Admin 用）。 | 管理員 |
| `GET` | `/api/admin/config` | 取得全域爬蟲配置（讀取 config_global.yaml）。 | 管理員 |
| `PATCH` | `/api/admin/config` | 修改全域配置（僅允許修改 crawler 區塊下的安全欄位）。 | 管理員 |
| `GET` | `/api/admin/smtp` | 取得 SMTP 配置狀態（密碼遮罩，從環境變數讀取）。 | 管理員 |
| `POST` | `/api/admin/smtp/test` | 寄送測試郵件以驗證 SMTP 設定。 | 管理員 |
| `GET` | `/api/admin/logs` | 查閱系統操作日誌（支援事件類型、使用者 ID 及時間範圍篩選）。 | 管理員 |

## 4. 系統與文件 API

| 方法 | 路徑 | 說明 | 權限 |
|------|------|------|------|
| `GET` | `/api/health` | 服務健康檢查端點（供 CI/CD 或 Load Balancer 使用）。 | 公開 |
