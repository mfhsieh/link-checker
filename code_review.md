# Code Review 報告：ext-link-checker

> **審查範圍**：全專案 Python 後端 + 前端靜態資源  
> **日期**：2026-06-07  
> **狀態**：僅審查，尚未修改任何程式碼

---

## 📊 整體評估

| 面向 | 評分 | 說明 |
|------|------|------|
| 安全性 | ★★★★☆ | 整體相當紮實；有幾個可強化點 |
| 程式碼品質 | ★★★★☆ | 結構清晰、文件完整 |
| 架構設計 | ★★★★☆ | 關注點分離良好 |
| 錯誤處理 | ★★★☆☆ | 局部有需要改進的地方 |
| 可維護性 | ★★★★☆ | 模組化程度高 |
| 測試覆蓋率 | ★☆☆☆☆ | 幾乎無自動化測試 |

---

## 🐛 問題彙整

### 🔴 高嚴重性（Bugs / 安全疑慮）

---

#### BUG-01：`email_sender.py` — Console Mode 中使用了未定義變數

**檔案**：[email_sender.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/email_sender.py#L101-L110)  
**行號**：107

```python
# send_invitation_email() 中：
if settings.SMTP_CONSOLE_MODE:
    logger.info(
        "[SMTP Console Mode] 邀請郵件（未實際寄送）:\n"
        "  收件者: %s\n  Subject: %s\n  登入連結: %s\n  邀請碼: %s",
        to_email,
        msg["Subject"],
        login_url,          # ← NameError！login_url 在這個作用域未定義
        invitation_token,
    )
    return True
```

`login_url` 是在 `_build_invitation_email()` 內部定義的區域變數，在 `send_invitation_email()` 中根本不存在。每當 `SMTP_CONSOLE_MODE=true` 時，呼叫此函式必定丟出 `NameError`，導致邀請功能完全失效。

---

#### BUG-02：`crawler/core.py` — 讀取大型 response 時可能造成記憶體暴漲

**檔案**：[core.py](file:///home/mfhsieh/projects/python/ext-link-checker/crawler/core.py#L149-L174)  
**行號**：149–167

```python
with client.stream("GET", url) as response:
    response.raise_for_status()
    # ... MIME 類型檢查 ...
    response.read()   # ← 若目標頁面非常大，整個 response 都會載入記憶體
    return (response.text, ...)
```

雖然已設定了 MIME 類型過濾，但在通過過濾之後才呼叫 `response.read()`，若目標頁面是幾十 MB 的 HTML（例如大型資料頁或錯誤頁），仍然會無限制地載入到記憶體。建議加入 `max_content_length` 上限保護。

---

#### SEC-01：CSRF Token 使用簡單字串比對（非 constant-time）

**檔案**：[deps.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/deps.py#L212)  
**行號**：212

```python
if csrf_cookie != csrf_header:
```

Python 的 `!=` 字串比對並非 constant-time，存在 timing side-channel 攻擊的理論風險。建議改用 `secrets.compare_digest()`：

```python
if not secrets.compare_digest(csrf_cookie, csrf_header):
```

雖然在 Double Submit Cookie 模式下實際可利用性低，但這是最佳實務。

---

#### SEC-02：`crawler/manager.py` — `PRAGMA foreign_keys=ON` 未在 Crawler DB 啟用

**檔案**：[manager.py](file:///home/mfhsieh/projects/python/ext-link-checker/crawler/manager.py#L118-L125)  
**行號**：118–125

Auth DB 在 `db.py` 中有啟用 `PRAGMA foreign_keys=ON`，但 Crawler DB 的 `__init__` 裡的 PRAGMA 設定卻沒有加上這行。`CrawlQueue` 與 `ExternalLink` 有 ForeignKey 指向 `jobs.id`，若 FK enforcement 關閉，理論上可能插入懸空外鍵紀錄（雖然 cascade 刪除是透過 ORM 處理，不依賴 DB 層，但仍不一致）。

---

#### SEC-03：`admin/router.py` — 全域配置更新的輸入值未作型別/值域驗證

**檔案**：[admin/router.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/admin/router.py#L420-L516)  
**行號**：462–478

```python
crawler_updates = body.get("crawler", {})
# 只過濾了「不允許的欄位名稱」，但沒有驗證欄位的值
```

目前只有白名單欄位名稱檢查，但沒有驗證值的型別與範圍。惡意 Admin 可以提交 `{"crawler": {"timeout": -999}}` 等異常值直接寫入 YAML 檔。雖然之後的 CLI 合併邏輯有 `_enforce_crawler_limits`，但 API 層本身應先做基礎驗證。

---

### 🟡 中嚴重性（邏輯問題 / 潛在風險）

---

#### ISSUE-01：`backend/jobs/service.py` — 子程序 stdout/stderr 靜默捨棄，難以 Debug

**檔案**：[jobs/service.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/jobs/service.py#L111-L117)

```python
proc = subprocess.Popen(
    [sys.executable, cli_path, "--resume", job_id],
    cwd=project_root,
    stdout=subprocess.DEVNULL,   # ← 子程序所有輸出都被丟棄
    stderr=subprocess.DEVNULL,
    close_fds=True,
)
```

爬蟲子程序若發生啟動錯誤（如 import error、DB 連線失敗），其 stderr 輸出全部被 DEVNULL 捨棄，從 Web 端完全看不到錯誤原因，任務狀態也可能停在 `running` 而無法自動還原。建議至少將 stderr 重導向至 log 檔案。

---

#### ISSUE-02：`backend/deps.py` — 全域 `_JOB_MANAGER` 的懶加載沒有執行緒鎖

**檔案**：[deps.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/deps.py#L45-L54)

```python
_JOB_MANAGER: JobManager | None = None

def get_job_manager() -> JobManager:
    global _JOB_MANAGER
    if _JOB_MANAGER is None:        # ← 競爭條件（race condition）
        _JOB_MANAGER = JobManager(db_url=settings.CRAWLER_DB_URL)
    return _JOB_MANAGER
```

在 Uvicorn workers 並發啟動時，可能有多個 coroutine 同時進入 `if _JOB_MANAGER is None`，建立多個 `JobManager` 實例（含多個 SQLAlchemy engine）。雖然因 GIL 而實際問題較小，但屬於不安全的做法。建議使用 FastAPI lifespan 事件或 threading.Lock。

---

#### ISSUE-03：`crawler/manager.py` — `get_job()` 回傳的 ORM 物件在 Session 關閉後為 detached

**檔案**：[manager.py](file:///home/mfhsieh/projects/python/ext-link-checker/crawler/manager.py#L307-L318)

```python
def get_job(self, job_id: str) -> Job | None:
    with self.SessionLocal() as session:
        return session.query(Job).filter(Job.id == job_id).first()
        # ← with block 結束後 session 已關閉，但物件被回傳出去
```

回傳的 `Job` ORM 物件在 Session 關閉後進入 detached 狀態，呼叫端若存取 lazy-loaded 關聯屬性（如 `.queues`、`.external_links`），會引發 `DetachedInstanceError`。目前程式碼只存取基本欄位，暫時無問題，但這是不穩定的設計。

建議改用 `Session.expunge()` + `make_transient()` 明確處理，或改用 `expire_on_commit=False` 搭配適當策略。

---

#### ISSUE-04：`backend/jobs/service.py` — `_running_processes` 記憶體洩漏

**檔案**：[jobs/service.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/jobs/service.py#L35)

```python
_running_processes: dict[str, subprocess.Popen] = {}
```

已結束的子程序 `Popen` 物件會一直留在此 dict 中，不會自動清除。隨著任務數量增加，這個 dict 會無限成長。`Popen` 物件持有子程序的 file descriptor，可能造成 fd 洩漏。

建議在任務狀態轉為 `completed`/`error`/`paused` 時主動從 dict 中移除，或定期清理已結束的進程。

---

#### ISSUE-05：`backend/jobs/router.py` — 匯出時 `page_size=999999` 可能引發記憶體問題

**檔案**：[jobs/router.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/jobs/router.py#L386-L388)

```python
query_obj = job_service.JobResultQuery(
    ...
    page=1,
    page_size=999999,  # ← 將全部結果載入記憶體
)
```

`export_results` 與 `export_full_report` 端點使用 `page_size=999999`，等同於「把資料庫中所有記錄都撈出來放到記憶體」。若一個任務有數十萬筆外部連結，此 API 呼叫可能消耗大量記憶體並導致 OOM。建議改用資料庫游標（cursor）或串流（streaming response）的方式處理匯出。

---

### 🟢 低嚴重性（邏輯問題 / 程式碼品質）

---

#### ISSUE-06：`backend/auth/service.py` — 邀請 token 在設密前可重複使用

**檔案**：[auth/service.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/auth/service.py#L173-L233)

首次邀請登入成功後（呼叫 `authenticate_with_invitation`），並**沒有**立刻將 `Invitation.used_at` 標記為已使用。邀請 token 只有在 `set_first_password()` 完成後才會被標記。

若使用者在登入後、設密前離開，然後用同一個邀請 token 再次登入，系統不會阻擋，可能建立多個有效的 first-login session。這是否符合預期行為，值得確認。

---

#### ISSUE-07：`cli.py` — `_handle_resume_or_create()` 在 `--resume` 時仍執行 crawler config 合併

**檔案**：[cli.py](file:///home/mfhsieh/projects/python/ext-link-checker/cli.py#L677-L685)

```python
crawler_config = merge_and_validate_crawler_config(config, global_config)  # ← 先合併（不必要）

if args.resume is not None:
    manager.run_job(job_id=args.resume, force=args.force)  # ← 不傳 crawler_config
    return
```

在 `--resume` 模式下，`crawler_config` 確實沒有被使用，但前面的 `merge_and_validate_crawler_config` 呼叫仍然白白執行了。若 `--config` 指定的 YAML 有語法錯誤，還可能在不應該失敗的 resume 操作中導致錯誤。

---

#### QUALITY-01：`email_sender.py` — 三個 SMTP 函式有大量重複程式碼

**檔案**：[email_sender.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/email_sender.py)

`send_invitation_email()`、`send_test_email()`、`send_notification_email()` 三個函式都有完全相同的 SMTP 連線邏輯（共約 25 行重複）。建議抽取出 `_send_email(msg: EmailMessage) -> bool` 私有函式來消除重複。

---

#### QUALITY-02：`jobs/router.py` — `create_job` 直接 import CLI 模組函式

**檔案**：[jobs/router.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/jobs/router.py#L148)

```python
from cli import merge_and_validate_crawler_config
```

Web 後端模組直接 import CLI 模組的函式，造成不合理的耦合。`merge_and_validate_crawler_config` 是業務邏輯，應該移到 `crawler/` 或 `backend/` 的共用模組中，而不是放在 CLI 入口點。

---

#### QUALITY-03：`jobs/router.py` — `get_default_config` 直接 import admin router 常數

**檔案**：[jobs/router.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/jobs/router.py#L85)

```python
from backend.admin.router import DEFAULT_GLOBAL_CONFIG
```

jobs router 直接引用 admin router 的常數，形成同層模組間的不必要依賴。`DEFAULT_GLOBAL_CONFIG` 應移至共用設定或常數模組。

---

#### QUALITY-04：`admin/router.py` — `ALLOWED_CRAWLER_KEYS` 定義在函式內部

**檔案**：[admin/router.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/admin/router.py#L453-L459)

`ALLOWED_CRAWLER_KEYS` 集合被定義在 `update_config()` 函式的內部（每次呼叫都重建）。應提升為模組層級常數，且與 `cli.py` 中的 `allowed_crawler_keys` 重複定義，應統一管理。

---

#### QUALITY-05：`manager.py` — `export_job_results()` 函式過長（約 265 行）

**檔案**：[manager.py](file:///home/mfhsieh/projects/python/ext-link-checker/crawler/manager.py#L806-L1072)

`export_job_results()` 包含 4 種 group_by 模式 × 2 種格式（CSV/JSON），深度嵌套超過 5 層，整個函式超過 260 行。應比照 `jobs/service.py` 的做法，拆分成各個輔助函式。

---

#### QUALITY-06：`auth/service.py` — `change_password` 與 `set_first_password` 的防護不對稱

**檔案**：[auth/service.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/auth/service.py#L494)

`set_first_password()` 有做 `verify_password(new_password, user.password_hash)` 的 hash 層驗證，確保新密碼與舊 hash 不同；但 `change_password()` 只用明文字串比對 `current_password == new_password`，無法防止「略有不同的相同語意密碼」（如加空格）。

---

#### QUALITY-07：`config.py` — `Settings` 設計限制了測試彈性

**檔案**：[config.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/config.py)

`Settings` 是一個普通 class，所有屬性都是 class-level 變數（在模組匯入時就求值），而非在 `__init__` 中。加上 `lru_cache`，導致測試中無法透過替換環境變數來重新建立 `Settings`，可測試性受限。

---

#### QUALITY-08：`manager.py` — `run_job` 中 `status_code` 變數與外部命名衝突

**檔案**：[manager.py](file:///home/mfhsieh/projects/python/ext-link-checker/crawler/manager.py#L590)

```python
for link, ip, status_code, err_msg in results:
```

迴圈內的 `status_code` 與前面 `queue_item.status_code` 同名（不同作用域），造成閱讀混淆。建議重命名為 `link_status_code` 等更具區分性的名稱。

---

#### QUALITY-09：缺乏自動化測試

整個 `test/` 目錄僅有 `test_server/` 下的手動測試伺服器，沒有任何 pytest 單元測試或整合測試。`requirements.txt` 中 pytest 也被注釋掉了。考量到這是一個含有爬蟲邏輯、Session 管理、權限控制等複雜業務的系統，缺乏自動化測試是最大的維護風險。

---

#### QUALITY-10：`admin/router.py` — 跨 DB 刪除無原子性保護

**檔案**：[admin/router.py](file:///home/mfhsieh/projects/python/ext-link-checker/backend/admin/router.py#L274-L286)

```python
# 1. 先刪 Crawler DB → commit 成功
# 2. 再刪 Auth DB → 若此處 commit 失敗，兩邊資料不一致
```

這是跨資料庫的操作，沒有分散式事務的保護。雖然 SQLite 下 commit 失敗機率極低，但應在程式碼中加上說明，記錄此已知限制。

---

## 📋 問題彙整表

| ID | 嚴重性 | 類型 | 檔案 | 摘要 |
|----|--------|------|------|------|
| BUG-01 | 🔴 高 | Bug | email_sender.py:107 | Console Mode 使用未定義的 `login_url` 變數 |
| BUG-02 | 🔴 高 | 效能/穩定性 | core.py:167 | 大型 response 無限制載入記憶體 |
| SEC-01 | 🔴 高 | 安全性 | deps.py:212 | CSRF token 比對未用 constant-time |
| SEC-02 | 🟡 中 | 安全性 | manager.py:118 | Crawler DB 未啟用 `foreign_keys=ON` |
| SEC-03 | 🟡 中 | 安全性 | admin/router.py:462 | 全域配置更新缺乏值域驗證 |
| ISSUE-01 | 🟡 中 | 可觀測性 | jobs/service.py:114 | 子程序錯誤輸出被靜默丟棄 |
| ISSUE-02 | 🟡 中 | 執行緒安全 | deps.py:51 | JOB_MANAGER 懶加載缺執行緒鎖 |
| ISSUE-03 | 🟡 中 | 資料庫 | manager.py:318 | `get_job()` 回傳 detached ORM 物件 |
| ISSUE-04 | 🟡 中 | 資源洩漏 | jobs/service.py:35 | `_running_processes` 不會自動清理 |
| ISSUE-05 | 🟡 中 | 記憶體 | jobs/router.py:387 | 匯出使用 page_size=999999 |
| ISSUE-06 | 🟢 低 | 邏輯 | auth/service.py:222 | 邀請 token 在設密前可重複使用 |
| ISSUE-07 | 🟢 低 | 邏輯 | cli.py:677 | Resume 模式仍執行不必要的 config 合併 |
| QUALITY-01 | 🟢 低 | 重構 | email_sender.py | SMTP 連線邏輯三重複製 |
| QUALITY-02 | 🟢 低 | 架構 | jobs/router.py:148 | 後端直接 import CLI 模組函式 |
| QUALITY-03 | 🟢 低 | 架構 | jobs/router.py:85 | jobs router 直接 import admin router 常數 |
| QUALITY-04 | 🟢 低 | 重構 | admin/router.py:453 | 允許欄位集合重複定義於函式內部 |
| QUALITY-05 | 🟢 低 | 可維護性 | manager.py:806 | `export_job_results()` 過長 |
| QUALITY-06 | 🟢 低 | 安全性 | auth/service.py:494 | `change_password` 防護不如 `set_first_password` |
| QUALITY-07 | 🟢 低 | 可測試性 | config.py | Settings 類別設計限制測試彈性 |
| QUALITY-08 | 🟢 低 | 可讀性 | manager.py:590 | run_job 內變數命名易混淆 |
| QUALITY-09 | 🟢 低 | 測試 | 全專案 | 缺乏自動化測試 |
| QUALITY-10 | 🟢 低 | 資料一致性 | admin/router.py:274 | 跨 DB 刪除無原子性保護 |

---

## ✅ 做得好的地方

- **安全設計扎實**：bcrypt 密碼雜湊、Session Token SHA-256 儲存、HTTP-only Cookie、CSRF Double Submit、帳號鎖定機制——這些都是正確實作的。
- **SSRF 防禦**：`is_safe_ip()` 函式阻擋了私有/迴路 IP，`CrawlerCore.fetch()` 在發送請求前確實執行 IP 驗證。
- **CSP 安全標頭**：`SecurityHeadersMiddleware` 有設定 `X-Frame-Options`、`X-Content-Type-Options`、`Content-Security-Policy`，並在 TODO 中標記了 unsafe-inline 的改進方向。
- **白名單欄位過濾**：設定合併邏輯有明確的 allowed key 白名單，防止任意欄位注入。
- **Path Traversal 防禦**：`load_config()` 中的 `allowed_directory` 參數使用 `os.path.realpath` + `commonpath` 進行路徑驗證。
- **程式文件完整**：所有公開函式均有詳盡的 docstring，包含 Args、Returns、Raises 說明。
- **模組化清晰**：crawler、backend/auth、backend/jobs、backend/admin 各自獨立，關注點分離良好。

---

> 請確認您希望修改哪些項目，我再逐一進行修改。
