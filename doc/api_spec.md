# API 完整規格書 (API Specification)

本文件由系統自動從 FastAPI OpenAPI Schema 萃取產生，詳細記錄所有端點、參數及回傳格式。

## POST /api/auth/login
**摘要**: Login

**說明**: 使用者登入。

支援兩種登入模式：
1. 首次登入：提供 email + token（邀請 UUID）
2. 一般登入：提供 email + password

登入成功後設定 HTTP-only Session Cookie 與 CSRF Cookie。


**Args**:
- `body` (LoginRequest): 登入請求內容，包含 email、密碼或邀請 token。
- `request` (Request): FastAPI 請求物件。
- `response` (Response): FastAPI 回應物件，用於設定 Cookie。
- `background_tasks` (BackgroundTasks): 用於背景執行 GC。
- `db` (DBSession): Auth 資料庫 Session。


**Returns**:
- `dict[str, object]`: 登入結果，包含是否為首次登入 (is_first_login) 與使用者資訊 (user)。


**Raises**:
- `HTTPException 400`: 若參數不完整（同時提供或同時缺少密碼與 token）。
- `HTTPException 401`: 若驗證失敗或帳號異常。

**標籤**: auth

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `LoginRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/auth/set-password
**摘要**: Set Password

**說明**: 首次登入後的強制密碼設定。

只允許 is_first_login=True 的 Session 呼叫此端點。
密碼設定完成後，Session 狀態轉為正常，帳號啟用。


**Args**:
- `body` (SetPasswordRequest): 新密碼設定請求。
- `db` (DBSession): Auth 資料庫 Session。
- `current_session` (AuthSession): 當前的 Session 物件。
- `_csrf` (None): CSRF 防禦依賴。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 403`: 若當前 Session 不是首次登入 Session。
- `HTTPException 422`: 若新密碼不符合安全強度規範。

**標籤**: auth

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `SetPasswordRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/auth/logout
**摘要**: Logout

**說明**: 登出並清除 Session Token。


**Args**:
- `response` (Response): FastAPI 回應物件，用於清除 Cookie。
- `request` (Request): FastAPI 請求物件，用於讀取 Cookie。
- `background_tasks` (BackgroundTasks): 用於背景執行 GC。
- `db` (DBSession): Auth DB Session。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 成功訊息。

**標籤**: auth

### 回應 (Responses)
- **200**: Successful Response
---

## GET /api/auth/me
**摘要**: Get Me

**說明**: 取得當前已登入使用者的基本資訊。


**Args**:
- `current_user` (User): 當前登入的使用者物件。


**Returns**:
- `dict[str, object]`: 使用者的基本資訊。

**標籤**: auth

### 回應 (Responses)
- **200**: Successful Response
---

## PATCH /api/auth/password
**摘要**: Change Password

**說明**: 已登入使用者修改密碼（需提供現有密碼進行驗證）。


**Args**:
- `body` (ChangePasswordRequest): 變更密碼的請求內容。
- `db` (DBSession): Auth DB Session。
- `current_user` (User): 當前登入的使用者物件。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 422`: 現有密碼錯誤或新密碼不符合安全標準時拋出。

**標籤**: auth

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `ChangePasswordRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/auth/forgot-password
**摘要**: Forgot Password

**說明**: 申請重設密碼。

無論信箱是否存在，皆回傳相同成功訊息，防止帳號列舉攻擊。
（註：此為未認證訪客端點，無 Session/Cookie 依賴，故不實施 CSRF 防禦，改採 IP 限速機制）


**Args**:
- `body` (ForgotPasswordRequest): 包含 email 的請求內容。
- `request` (Request): FastAPI 請求物件。
- `db` (DBSession): Auth DB Session。


**Returns**:
- `dict[str, str]`: 成功訊息。

**標籤**: auth

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `ForgotPasswordRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/auth/reset-password
**摘要**: Reset Password

**說明**: 重設密碼。

驗證 Token 後設定新密碼，並使該使用者所有 Session 失效。
（註：此為未認證訪客端點，無 Session/Cookie 依賴，故不實施 CSRF 防禦）


**Args**:
- `body` (ResetPasswordRequest): 包含 token 與新密碼的請求內容。
- `request` (Request): FastAPI 請求物件。
- `db` (DBSession): Auth DB Session。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 400`: 若 Token 無效、過期，或新密碼強度不足。

**標籤**: auth

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `ResetPasswordRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/jobs/default-config
**摘要**: Get Default Config

**說明**: 取得任務預設的全域配置，供前端建立任務時填入預設值與限制。


**Args**:
- `_current_user` (User): 當前登入的使用者物件。


**Returns**:
- `dict[str, object]`: 允許前端使用的預設配置過濾結果。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
---

## GET /api/jobs
**摘要**: List Jobs

**說明**: 列出當前使用者的所有任務。


**Args**:
- `status_filter` (str | None): 依任務狀態篩選。
- `current_user` (User): 當前登入的使用者物件。
- `manager` (JobManager): JobManager 實例。


**Returns**:
- `list[dict[str, object]]`: 任務清單。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/jobs
**摘要**: Create Job

**說明**: 建立新的爬蟲任務。


**Args**:
- `body` (CreateJobRequest): 建立任務的請求內容。
- `current_user` (User): 當前登入的使用者物件。
- `manager` (JobManager): JobManager 實例。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, object]`: 新建任務的 ID 與訊息。


**Raises**:
- `HTTPException 500`: 建立任務失敗時拋出。

**標籤**: jobs

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `CreateJobRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/jobs/{job_id}
**摘要**: Get Job

**說明**: 取得任務詳情（含進度）。


**Args**:
- `job_id` (str): 欲查詢的任務 ID。
- `current_user` (User): 當前登入的使用者。
- `manager` (JobManager): JobManager 實例。


**Returns**:
- `dict[str, object]`: 任務詳情與進度。


**Raises**:
- `HTTPException 404`: 找不到任務或無權限時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## DELETE /api/jobs/{job_id}
**摘要**: Delete Job

**說明**: 刪除任務及所有相關資料。


**Args**:
- `job_id` (str): 欲刪除的任務 ID。
- `current_user` (User): 當前登入的使用者。
- `manager` (JobManager): JobManager 實例。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 404`: 若任務不存在時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/jobs/{job_id}/start
**摘要**: Start Job

**說明**: 啟動任務（spawn 爬蟲子程序）。


**Args**:
- `job_id` (str): 欲啟動的任務 ID。
- `current_user` (User): 當前登入的使用者。
- `manager` (JobManager): JobManager 實例。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 400`: 若任務狀態不允許啟動時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/jobs/{job_id}/pause
**摘要**: Pause Job

**說明**: 暫停任務（協同暫停，更新 DB 狀態）。


**Args**:
- `job_id` (str): 欲暫停的任務 ID。
- `current_user` (User): 當前登入的使用者。
- `manager` (JobManager): JobManager 實例。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 400`: 若操作失敗時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/jobs/{job_id}/resume
**摘要**: Resume Job

**說明**: 恢復已暫停的任務（只允許 paused 狀態）。


**Args**:
- `job_id` (str): 欲恢復的任務 ID。
- `current_user` (User): 當前登入的使用者。
- `manager` (JobManager): JobManager 實例。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 400`: 若任務非暫停狀態時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/jobs/{job_id}/reset
**摘要**: Reset Job

**說明**: 重置任務（清除結果並回到 pending 狀態）。


**Args**:
- `job_id` (str): 欲重置的任務 ID。
- `current_user` (User): 當前登入的使用者。
- `manager` (JobManager): JobManager 實例。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 400`: 若操作失敗時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/jobs/{job_id}/retry-failed
**摘要**: Retry Failed Job

**說明**: 局部重試任務中的失敗項目。


**Args**:
- `job_id` (str): 欲重試的任務 ID。
- `current_user` (User): 當前登入的使用者。
- `manager` (JobManager): JobManager 實例。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 400`: 若操作失敗時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/jobs/{job_id}/transfer
**摘要**: Transfer Job

**說明**: 將任務移交給其他使用者。


**Args**:
- `job_id` (str): 欲移交的任務 ID。
- `body` (TransferJobRequest): 包含目標使用者信箱的請求內容。
- `current_user` (User): 當前登入的使用者。
- `manager` (JobManager): JobManager 實例。
- `auth_db` (DBSession): Auth DB Session。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 400`: 目標使用者不存在或狀態異常時拋出。

**標籤**: jobs

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `TransferJobRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/jobs/{job_id}/results
**摘要**: Get Results

**說明**: 外連結果列表（支援篩選、搜尋、去重聚合與分頁）。


**Args**:
- `job_id` (str): 任務 ID。
- `query_args` (ResultsQueryArgs): 結果查詢參數。
- `current_user` (User): 當前登入的使用者。
- `db` (DBSession): Crawler DB Session。


**Returns**:
- `dict[str, object]`: 查詢結果。


**Raises**:
- `HTTPException 404`: 找不到任務時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/jobs/{job_id}/results/summary
**摘要**: Get Results Summary

**說明**: 取得任務結果統計摘要。


**Args**:
- `job_id` (str): 任務 ID。
- `exclude` (str | None): 要排除的目標網域。
- `group_by` (str): 聚合方式。
- `current_user` (User): 當前登入的使用者。
- `db` (DBSession): Crawler DB Session。


**Returns**:
- `dict[str, object]`: 任務結果統計。


**Raises**:
- `HTTPException 404`: 找不到任務時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/jobs/{job_id}/diff
**摘要**: Get Job Diff

**說明**: 比對兩個任務的外連結果差異 (支援排除網域)。

以 job_id 作為基準 (舊任務)，compare_with 作為對照 (新任務)。


**Args**:
- `job_id` (str): 基準任務 ID。
- `compare_with` (str): 對照任務 ID。
- `exclude` (str | None): 要排除的目標網域。
- `current_user` (User): 當前登入的使用者。
- `db` (DBSession): Crawler DB Session。


**Returns**:
- `dict[str, object]`: 差異比對報表。


**Raises**:
- `HTTPException 404`: 找不到任務時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/jobs/{job_id}/internal-results/summary
**摘要**: Get Internal Results Summary

**說明**: 取得任務內部網頁爬取失敗的統計摘要。


**Args**:
- `job_id` (str): 任務 ID。
- `group_by` (str): 聚合方式。
- `current_user` (User): 當前登入的使用者。
- `db` (DBSession): Crawler DB Session。


**Returns**:
- `dict[str, object]`: 內部結果統計。


**Raises**:
- `HTTPException 404`: 找不到任務或無權限存取時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/jobs/{job_id}/internal-results
**摘要**: Get Internal Results

**說明**: 取得內部網頁爬取失敗的紀錄列表（支援分頁）。


**Args**:
- `job_id` (str): 任務 ID。
- `page` (int): 頁碼。
- `page_size` (int): 每頁筆數。
- `current_user` (User): 當前登入的使用者。
- `db` (DBSession): Crawler DB Session。


**Returns**:
- `dict[str, object]`: 包含失敗紀錄列表與分頁資訊的字典。


**Raises**:
- `HTTPException 404`: 找不到任務或無權限存取時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/jobs/{job_id}/results/export
**摘要**: Export Results

**說明**: 匯出外連結果（CSV 或 JSON 格式下載）。

查詢參數：
- filter: dead / broken / insecure
- group_by: 聚合模式 (none / target / source / domain)
- fmt: csv 或 json（預設 csv）


**Args**:
- `job_id` (str): 任務 UUID。
- `query_args` (ExportQueryArgs): 匯出查詢參數，含過濾條件、聚合設定與格式。
- `current_user` (User): 當前登入使用者。
- `db` (DBSession): Crawler 資料庫 Session。


**Returns**:
- `Response`: 包含匯出檔案內容的 FastAPI Response 物件。


**Raises**:
- `HTTPException 404`: 若任務不存在或不屬於當前使用者。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/jobs/{job_id}/internal-results/export
**摘要**: Export Internal Results

**說明**: 匯出內部失效結果（CSV 或 JSON 格式下載）。


**Args**:
- `job_id` (str): 任務 UUID。
- `query_filter` (str | None): 狀態過濾條件。
- `group_by` (str): 聚合方式。
- `fmt` (str): 輸出格式。
- `current_user` (User): 當前登入使用者。
- `db` (DBSession): Crawler 資料庫 Session。


**Returns**:
- `Response`: 包含匯出檔案內容的 FastAPI Response 物件。


**Raises**:
- `HTTPException 404`: 若任務不存在或不屬於當前使用者。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/jobs/{job_id}/export/full
**摘要**: Export Full Report

**說明**: 匯出完整報表 (ZIP 壓縮檔)，內含爬取紀錄與外連清單。


**Args**:
- `job_id` (str): 任務 ID。
- `background_tasks` (BackgroundTasks): FastAPI 背景任務，用於清理暫存檔。
- `current_user` (User): 當前登入的使用者。
- `db` (DBSession): Crawler DB Session。


**Returns**:
- `Response`: 檔案下載回應。


**Raises**:
- `HTTPException 404`: 找不到任務時拋出。

**標籤**: jobs

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/admin/users
**摘要**: List Users

**說明**: 列出所有使用者帳號。


**Args**:
- `status_filter` (str | None): (選填) 依帳號狀態篩選。
- `auth_db` (DBSession): Auth DB 的 SQLAlchemy Session。
- `_admin` (User): 當前管理員物件。


**Returns**:
- `list[dict[str, object]]`: 系統中所有使用者的資訊陣列。

**標籤**: admin

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/admin/users
**摘要**: Create User

**說明**: 新增使用者並寄送邀請郵件。


**Args**:
- `body` (CreateUserRequest): 建立使用者的請求內容（含 email）。
- `auth_db` (DBSession): Auth DB 的 SQLAlchemy Session。
- `_admin` (User): 當前管理員物件。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, object]`: 操作成功與邀請狀態訊息。

**標籤**: admin

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `CreateUserRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **201**: Successful Response
- **422**: Validation Error
---

## PATCH /api/admin/users/{user_id}
**摘要**: Update User

**說明**: 修改帳號狀態或角色。帳號停用時自動清除所有 Session。


**Args**:
- `user_id` (str): 欲修改的使用者 ID。
- `body` (UpdateUserRequest): 欲修改的狀態或角色內容。
- `request` (Request): FastAPI 的 Request 物件（供紀錄 IP 使用）。
- `auth_db` (DBSession): Auth DB 的 SQLAlchemy Session。
- `current_admin` (User): 當前執行操作的管理員物件。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 操作成功訊息。

**標籤**: admin

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `UpdateUserRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## DELETE /api/admin/users/{user_id}
**摘要**: Delete User

**說明**: 刪除帳號及所有關聯資料（含 Crawler DB 中的任務）。

跨庫刪除順序（§12.4）：先刪 Crawler DB 資料，再刪 Auth DB 帳號。


**Args**:
- `user_id` (str): 被刪除使用者的 UUID。
- `request` (Request): FastAPI Request。
- `background_tasks` (BackgroundTasks): 用於發送背景清理任務。
- `auth_db` (DBSession): Auth 資料庫 Session。
- `current_admin` (User): 當前操作的管理員使用者物件。
- `_csrf` (None): CSRF 防禦依賴。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 400`: 若管理員企圖刪除自己的帳號。
- `HTTPException 403`: 企圖直接刪除其他管理員帳號。
- `HTTPException 404`: 若被刪除的使用者不存在。

**標籤**: admin

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/admin/users/{user_id}/resend-invite
**摘要**: Resend Invite

**說明**: 重新寄送邀請郵件（重置邀請 token）。


**Args**:
- `user_id` (str): 目標使用者的 ID。
- `auth_db` (DBSession): Auth DB 的 SQLAlchemy Session。
- `_admin` (User): 當前管理員物件。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 成功寄送邀請的訊息。

**標籤**: admin

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/admin/jobs
**摘要**: List All Jobs

**說明**: 列出所有使用者的任務（Admin 全視圖）。


**Args**:
- `user_id` (str | None): (選填) 依使用者 ID 篩選。
- `status_filter` (str | None): (選填) 依任務狀態篩選。
- `manager` (JobManager): JobManager 實例。
- `_admin` (User): 當前管理員物件。


**Returns**:
- `list[dict[str, object]]`: 系統中所有任務的列表。

**標籤**: admin

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## POST /api/admin/jobs/{job_id}/takeover
**摘要**: Takeover Job

**說明**: 強制接管卡死任務（重置 running 狀態為 paused）。


**Args**:
- `job_id` (str): 欲接管的任務 ID。
- `request` (Request): FastAPI 請求物件。
- `manager` (JobManager): JobManager 實例。
- `auth_db` (DBSession): Auth DB 的 SQLAlchemy Session。
- `_admin` (User): 當前管理員物件。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 操作成功訊息。

**標籤**: admin

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## DELETE /api/admin/jobs/{job_id}
**摘要**: Admin Delete Job

**說明**: 強制刪除任意任務（Admin 用）。


**Args**:
- `job_id` (str): 欲刪除的任務 ID。
- `request` (Request): FastAPI 請求物件。
- `manager` (JobManager): JobManager 實例。
- `auth_db` (DBSession): Auth DB 的 SQLAlchemy Session。
- `_admin` (User): 當前管理員物件。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 操作成功訊息。

**標籤**: admin

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/admin/config
**摘要**: Get Config

**說明**: 取得全域爬蟲配置（讀取 config_global.yaml）。


**Args**:
- `_admin` (User): 當前管理員物件。


**Returns**:
- `dict[str, object]`: 目前的全域爬蟲配置。

**標籤**: admin

### 回應 (Responses)
- **200**: Successful Response
---

## PATCH /api/admin/config
**摘要**: Update Config

**說明**: 修改全域配置（僅允許修改 crawler 區塊下的安全欄位）。

採用 Pydantic 模型驗證：只允許修改 crawler.* 區塊中預先核准的欄位與型別，
禁止修改 db_url、logging（含 log_file 路徑）等系統級設定，
防範 Path Traversal 等攻擊與無效數值。


**Args**:
- `body` (UpdateConfigRequest): 包含欲修改設定值的結構。
- `request` (Request): FastAPI Request。
- `auth_db` (DBSession): Auth 資料庫 Session。
- `_admin` (User): 管理員使用者依賴，確保具備管理員權限。
- `_csrf` (None): CSRF 防禦依賴。


**Returns**:
- `dict[str, str]`: 成功訊息。


**Raises**:
- `HTTPException 422`: 若請求格式、數值不正確。
- `HTTPException 500`: 若寫入設定檔時發生 I/O 錯誤。

**標籤**: admin

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `UpdateConfigRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/admin/smtp
**摘要**: Get Smtp Config

**說明**: 取得 SMTP 配置狀態（密碼遮罩，從環境變數讀取）。


**Args**:
- `_admin` (User): 當前管理員物件。


**Returns**:
- `dict[str, object]`: SMTP 配置狀態，包含各種設定值。

**標籤**: admin

### 回應 (Responses)
- **200**: Successful Response
---

## POST /api/admin/smtp/test
**摘要**: Test Smtp

**說明**: 寄送測試郵件以驗證 SMTP 設定。


**Args**:
- `body` (SendTestEmailRequest): 請求內容，包含收件者信箱。
- `_admin` (User): 當前管理員物件。
- `_csrf` (None): CSRF 防禦標記。


**Returns**:
- `dict[str, str]`: 操作成功訊息。

**標籤**: admin

### 請求內容 (Request Body)
- **Content-Type**: `application/json`
- **Schema**: `SendTestEmailRequest` (參考下方 Schema 定義)

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/admin/logs
**摘要**: Get Logs

**說明**: 查閱系統操作日誌（支援事件類型、使用者 ID 及時間範圍篩選）。


**Args**:
- `query_args` (LogQueryArgs): 日誌查詢參數。
- `auth_db` (DBSession): Auth DB Session。
- `_admin` (User): 當前管理員物件。


**Returns**:
- `dict[str, object]`: 包含日誌項目列表與分頁資訊的字典。

**標籤**: admin

### 回應 (Responses)
- **200**: Successful Response
- **422**: Validation Error
---

## GET /api/health
**摘要**: Health Check

**說明**: 服務健康檢查端點（供 CI/CD 或 Load Balancer 使用）。


**Returns**:
- `dict[str, str]`: 服務健康狀態。

**標籤**: system

### 回應 (Responses)
- **200**: Successful Response
---

## ChangePasswordRequest
修改密碼的 Schema。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `current_password` | string | 是 |  |
| `new_password` | string | 是 |  |

---

## CrawlerConfigUpdate
Crawler 區塊配置更新請求結構。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `timeout` | integer | 否 |  |
| `delay` | number | 否 |  |
| `retries` | integer | 否 |  |
| `max_depth` | integer | 否 |  |
| `max_pages` | integer | 否 |  |
| `max_content_length` | integer | 否 |  |
| `max_redirects` | integer | 否 |  |
| `jitter_ratio` | number | 否 |  |
| `user_agent` | string | 否 |  |
| `proxy_url` | string | 否 |  |
| `ssl_exempt_domains` | array | 否 |  |
| `social_domains` | array | 否 |  |
| `domain_delays` | object | 否 |  |
| `ignore_extensions` | array | 否 |  |
| `ignore_regexes` | array | 否 |  |
| `mime_type_filter` | MimeTypeFilterConfig | 否 |  |
| `min_timeout` | integer | 否 |  |
| `max_timeout` | integer | 否 |  |
| `connect_timeout` | number | 否 |  |
| `external_check_timeout` | number | 否 |  |
| `min_connect_timeout` | number | 否 |  |
| `max_connect_timeout` | number | 否 |  |
| `min_external_check_timeout` | number | 否 |  |
| `max_external_check_timeout` | number | 否 |  |
| `min_delay` | number | 否 |  |
| `max_delay` | number | 否 |  |
| `min_retries` | integer | 否 |  |
| `max_retries` | integer | 否 |  |
| `max_max_depth` | integer | 否 |  |
| `max_max_pages` | integer | 否 |  |

---

## CreateJobRequest
建立任務請求的 Schema。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `start_url` | string | 是 |  |
| `target_domains` | array | 是 |  |
| `trusted_domains` | array | 否 |  |
| `ignore_extensions` | array | 否 |  |
| `ignore_regexes` | array | 否 |  |
| `max_depth` | integer | 否 |  |
| `max_pages` | integer | 否 |  |
| `delay` | number | 否 |  |
| `timeout` | integer | 否 |  |
| `connect_timeout` | number | 否 |  |
| `external_check_timeout` | number | 否 |  |
| `retries` | integer | 否 |  |
| `proxy_url` | string | 否 |  |
| `user_agent` | string | 否 |  |
| `ssl_exempt_domains` | array | 否 |  |
| `social_domains` | array | 否 |  |
| `domain_delays` | object | 否 |  |

---

## CreateUserRequest
建立使用者的請求結構。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `email` | string | 是 |  |

---

## ForgotPasswordRequest
忘記密碼申請的 Schema。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `email` | string | 是 |  |

---

## HTTPValidationError
| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `detail` | array | 否 |  |

---

## JobConfigSnapshot
任務設定快照的 Schema。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `target_domains` | array | 是 |  |
| `trusted_domains` | array | 是 |  |

---

## JobDetailResponse
任務詳情 API 回應的 Schema。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `id` | string | 是 |  |
| `start_url` | string | 是 |  |
| `status` | string | 是 |  |
| `created_at` | string | 是 |  |
| `updated_at` | string | 是 |  |
| `config` | JobConfigSnapshot | 是 |  |
| `progress` | JobProgress | 是 |  |
| `external_link_count` | integer | 是 |  |
| `is_running` | boolean | 是 |  |

---

## JobProgress
任務進度統計的 Schema。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `total` | integer | 是 |  |
| `completed` | integer | 是 |  |
| `warning` | integer | 是 |  |
| `skipped` | integer | 是 |  |
| `pending` | integer | 是 |  |
| `failed` | integer | 是 |  |

---

## LoginRequest
登入請求的 Schema。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `email` | string | 是 |  |
| `password` | string | 否 |  |
| `token` | string | 否 |  |

---

## MimeTypeFilterConfig
MimeType 過濾設定。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `enabled` | boolean | 是 |  |
| `allowed_types` | array | 是 |  |

---

## ResetPasswordRequest
重設密碼的 Schema。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `token` | string | 是 |  |
| `new_password` | string | 是 |  |

---

## SendTestEmailRequest
寄送測試郵件的請求結構。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `to_email` | string | 是 |  |

---

## SetPasswordRequest
首次登入設定密碼的 Schema。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `new_password` | string | 是 |  |

---

## TransferJobRequest
移交任務請求的 Schema。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `target_email` | string | 是 |  |

---

## UpdateConfigRequest
全域配置更新的請求結構。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `crawler` | CrawlerConfigUpdate | 是 |  |

---

## UpdateUserRequest
更新使用者的請求結構。

| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `status` | string | 否 |  |
| `role` | string | 否 |  |

---

## ValidationError
| 屬性名稱 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `loc` | array | 是 |  |
| `msg` | string | 是 |  |
| `type` | string | 是 |  |

---
