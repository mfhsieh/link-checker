"""
Auth DB 套件初始化模組。

此套件負責處理系統的核心使用者驗證與權限管理，包含以下模組：
- db.py: 負責建立與初始化驗證用的 SQLite 資料庫連線與 Session。
- models.py: 定義使用者 (User)、密碼重設 (PasswordReset) 與邀請碼 (InviteCode) 等資料庫 ORM 模型。
- password.py: 提供安全的密碼雜湊、比對與驗證工具。
- router.py: 提供註冊、登入、登出、權限檢查與密碼重設等公開的 API 路由。
- service.py: 實作使用者帳號管理、角色驗證與註冊流程等底層業務邏輯。
"""
