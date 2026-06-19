"""
後端應用程式的環境設定模組。

從環境變數讀取所有可配置的參數，並提供統一的 Settings 物件供全系統存取。
機密資料（密碼、金鑰）嚴禁硬編碼，必須由環境變數或 .env 檔案注入。
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

# 嘗試讀取 .env 檔案（如果存在的話）
load_dotenv()


class Settings:  # pylint: disable=too-few-public-methods
    """應用程式設定類別。

    所有設定值皆從環境變數讀取，若環境變數不存在則使用預設值。
    機密項目（如 SMTP_PASSWORD）在生產環境中必須透過環境變數提供。

    Attributes:
        APP_NAME (str): 應用程式名稱。
        DEBUG (bool): 是否啟用除錯模式。
        LOG_CONSOLE_LEVEL (str): 控制台日誌輸出等級（預設為 INFO）。
        LOG_FILE_LEVEL (str): 檔案日誌輸出等級（預設為 DEBUG）。
        LOG_FILE_PATH (str): 日誌檔案路徑。
        AUTH_DB_URL (str): 認證與授權資料庫的 SQLite 連接字串。
        CRAWLER_DB_URL (str): 爬蟲任務資料庫的 SQLite 連接字串。
        SQLITE_TIMEOUT (int): SQLite 連線超時時間（秒）。
        DB_POOL_SIZE (int): 資料庫連線池大小。
        DB_MAX_OVERFLOW (int): 資料庫連線池最大溢出大小。
        DB_POOL_PRE_PING (bool): 是否在取得連線前進行 pre-ping 測試。
        SESSION_COOKIE_NAME (str): 用於存放登入 Session Token 的 Cookie 名稱。
        SESSION_EXPIRE_SECONDS (int): Session Token 的有效時間（秒，預設為 8 小時）。
        SESSION_MAX_AGE_SECONDS (int): Session Token 的絕對有效時間上限（秒，預設為 7 天）。
        CSRF_TOKEN_HEADER (str): 前端請求傳遞 CSRF Token 的 HTTP 標頭名稱（預設為 X-CSRF-Token）。
        CSRF_COOKIE_NAME (str): 存放 CSRF Token 的 Cookie 名稱（預設為 csrf_token）。
        INVITATION_EXPIRE_SECONDS (int): 邀請碼有效時間（秒，預設為 72 小時）。
        BASE_URL (str): 後台系統之基礎 URL，用於組裝邀請與重設密碼連結。
        LOGIN_MAX_ATTEMPTS (int): 連續登入失敗次數閾值，超過後將暫時鎖定帳號。
        LOGIN_LOCKOUT_SECONDS (int): 登入失敗鎖定帳號的時間（秒）。
        PASSWORD_RESET_MAX_ATTEMPTS (int): 同一 IP 於時間窗口內重設密碼之申請次數上限。
        PASSWORD_RESET_WINDOW_SECONDS (int): 重設密碼次數限制的時間窗口長度（秒）。
        SMTP_HOST (str): SMTP 郵件伺服器主機。
        SMTP_PORT (int): SMTP 郵件伺服器連接埠。
        SMTP_USERNAME (str): SMTP 郵件發送服務帳號。
        SMTP_PASSWORD (str): SMTP 郵件發送服務密碼。
        SMTP_FROM_NAME (str): 寄信人顯示名稱。
        SMTP_FROM_EMAIL (str): 寄信人 Email 地址。
        SMTP_USE_TLS (bool): 是否啟用 STARTTLS 安全傳輸。
        SMTP_CONSOLE_MODE (bool): 開發環境下是否啟用 Console 模擬郵件發送。
        GLOBAL_CONFIG_PATH (str): 全域預設爬蟲設定檔 YAML 之路徑。
    """

    # ── 應用程式基本設定 ────────────────────────────────────────────────────────
    APP_NAME: str = os.environ.get("APP_NAME", "外部連結檢查系統")
    DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"

    # ── 系統日誌設定 ───────────────────────────────────────────────────────────
    LOG_CONSOLE_LEVEL: str = os.environ.get("LOG_CONSOLE_LEVEL", "INFO")
    LOG_FILE_LEVEL: str = os.environ.get("LOG_FILE_LEVEL", "DEBUG")
    LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "log/crawler.log")

    # ── 資料庫設定 ─────────────────────────────────────────────────────────────
    AUTH_DB_URL: str = os.environ.get("AUTH_DB_URL", "sqlite:///db/auth.db")
    CRAWLER_DB_URL: str = os.environ.get("CRAWLER_DB_URL", "sqlite:///db/crawler.db")
    SQLITE_TIMEOUT: int = int(os.environ.get("SQLITE_TIMEOUT", "30"))
    DB_POOL_SIZE: int = int(os.environ.get("DB_POOL_SIZE", "20"))
    DB_MAX_OVERFLOW: int = int(os.environ.get("DB_MAX_OVERFLOW", "20"))
    DB_POOL_PRE_PING: bool = os.environ.get("DB_POOL_PRE_PING", "true").lower() == "true"

    # ── Session 安全設定 ───────────────────────────────────────────────────────
    SESSION_COOKIE_NAME: str = os.environ.get("SESSION_COOKIE_NAME", "session_token")
    # Session 有效期（秒），預設 8 小時
    SESSION_EXPIRE_SECONDS: int = int(os.environ.get("SESSION_EXPIRE_SECONDS") or "28800")
    # Session 最大絕對有效期（秒），預設 7 天
    SESSION_MAX_AGE_SECONDS: int = int(os.environ.get("SESSION_MAX_AGE_SECONDS") or "604800")
    # CSRF Token 標頭名稱
    CSRF_TOKEN_HEADER: str = "X-CSRF-Token"
    CSRF_COOKIE_NAME: str = "csrf_token"

    # ── 邀請制設定 ─────────────────────────────────────────────────────────────
    # 邀請連結有效期（秒），預設 72 小時
    INVITATION_EXPIRE_SECONDS: int = int(os.environ.get("INVITATION_EXPIRE_SECONDS") or "259200")
    # 後台可訪問的基礎 URL（用於生成邀請連結）
    BASE_URL: str = os.environ.get("BASE_URL", "http://localhost:8000")

    # ── 登入保護設定 ───────────────────────────────────────────────────────────
    # 連續登入失敗次數閾值，超過後暫時鎖定帳號
    LOGIN_MAX_ATTEMPTS: int = int(os.environ.get("LOGIN_MAX_ATTEMPTS") or "3")
    # 帳號鎖定時間（秒），預設 15 分鐘
    LOGIN_LOCKOUT_SECONDS: int = int(os.environ.get("LOGIN_LOCKOUT_SECONDS") or "900")
    # 同一 IP 申請重設密碼的次數上限
    PASSWORD_RESET_MAX_ATTEMPTS: int = int(os.environ.get("PASSWORD_RESET_MAX_ATTEMPTS") or "3")
    # 重設密碼申請的限速時間窗口（秒）
    PASSWORD_RESET_WINDOW_SECONDS: int = int(os.environ.get("PASSWORD_RESET_WINDOW_SECONDS") or "900")

    # ── SMTP 郵件設定（透過環境變數提供，不存入資料庫）─────────────────────────
    SMTP_HOST: str = os.environ.get("SMTP_HOST", "localhost")
    SMTP_PORT: int = int(os.environ.get("SMTP_PORT") or "587")
    SMTP_USERNAME: str = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM_NAME: str = os.environ.get("SMTP_FROM_NAME", "外部連結檢查系統")
    SMTP_FROM_EMAIL: str = os.environ.get("SMTP_FROM_EMAIL", "noreply@example.com")
    SMTP_USE_TLS: bool = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    # 開發環境下啟用 console 模擬（不真實發送）
    SMTP_CONSOLE_MODE: bool = os.environ.get("SMTP_CONSOLE_MODE", "false").lower() == "true"

    # ── 全域爬蟲設定檔路徑 ─────────────────────────────────────────────────────
    GLOBAL_CONFIG_PATH: str = os.environ.get("GLOBAL_CONFIG_PATH", "config/config_global.yaml")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    取得設定單例（使用 lru_cache 確保全域共用同一份設定物件）。

    Returns:
        Settings: 應用程式設定物件。
    """
    return Settings()
