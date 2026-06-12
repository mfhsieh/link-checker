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
    """
    應用程式設定類別。

    所有設定值皆從環境變數讀取，若環境變數不存在則使用預設值。
    機密項目（如 SMTP_PASSWORD）在生產環境中必須透過環境變數提供。
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
    LOGIN_MAX_ATTEMPTS: int = int(os.environ.get("LOGIN_MAX_ATTEMPTS") or "5")
    # 帳號鎖定時間（秒），預設 15 分鐘
    LOGIN_LOCKOUT_SECONDS: int = int(os.environ.get("LOGIN_LOCKOUT_SECONDS") or "900")

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
