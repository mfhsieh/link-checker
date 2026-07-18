"""
爬蟲模組專屬的環境變數集中管理檔案。

為確保模組解耦（CLI-First），crawler 模組不依賴 backend.config，
而是自行管理其所需的維運環境變數。

模組層級常數/屬性：
    - PROXY_URL: 全域代理伺服器網址。
    - SSL_EXEMPT_DOMAINS: 全域 SSL 驗證豁免網域名單。
    - MAX_WORKERS: 外部連結探測的並發執行緒上限。
    - ALLOW_LOCAL_IPS: 是否允許存取內網 IP（預設為安全阻擋）。
    - SQLITE_TIMEOUT: SQLite 資料庫鎖定的逾時時間。
    - DB_POOL_SIZE: 資料庫連線池大小。
    - DB_MAX_OVERFLOW: 資料庫連線池的最大溢出數量。
    - DB_POOL_PRE_PING: 是否啟用 pre-ping 以確保連線有效性。
"""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class CrawlerEnv:  # pylint: disable=too-many-instance-attributes
    """
    爬蟲引擎專用環境變數資料結構。

    此資料類別 (Dataclass) 統一封裝所有從系統環境變數 (`os.environ`) 讀取的配置項，
    並於初始化時直接轉型為合適的型別。設定一經載入即凍結 (frozen=True)，不允許執行期修改。

    Attributes:
        proxy_url (str | None): 全域代理伺服器網址（例如 `http://user:pass@proxy:8080`），
            若無設定則為 None。
        ssl_exempt_domains (str | None): 全域的 SSL 驗證豁免網域名單，多筆時以逗號分隔。
        max_workers (int): 外部連結存活探測 (`ThreadPoolExecutor`) 的並發執行緒數量上限。
        allow_local_ips (bool): 是否允許爬蟲引擎存取內網私有 IP 位址（如 127.0.0.1）。
            強烈建議在生產環境維持 False 以防範 SSRF 攻擊。
        sqlite_timeout (int): SQLite 資料庫等待解除鎖定的最長逾時時間（秒）。
        db_pool_size (int): （非 SQLite 資料庫適用）預先建立的連線池基礎大小。
        db_max_overflow (int): （非 SQLite 資料庫適用）連線池在基礎大小之外，允許臨時溢出的最大連線數。
        db_pool_pre_ping (bool): （非 SQLite 資料庫適用）每次從連線池取得連線前，是否先進行輕量級連線測試。
    """

    # ── 爬蟲核心參數 ──
    proxy_url: str | None
    ssl_exempt_domains: str | None
    max_workers: int
    allow_local_ips: bool

    # ── 資料庫連線參數 ──
    sqlite_timeout: int
    db_pool_size: int
    db_max_overflow: int
    db_pool_pre_ping: bool


@lru_cache(maxsize=1)
def get_env() -> CrawlerEnv:
    """
    取得爬蟲專用的環境變數設定單例。

    Returns:
        CrawlerEnv: 爬蟲環境變數物件。
    """
    return CrawlerEnv(
        proxy_url=os.environ.get("CRAWLER_PROXY_URL"),
        ssl_exempt_domains=os.environ.get("CRAWLER_SSL_EXEMPT_DOMAINS"),
        max_workers=int(os.environ.get("CRAWLER_MAX_WORKERS", "50")),
        allow_local_ips=os.environ.get("CRAWLER_ALLOW_LOCAL_IPS", "false").lower() == "true",
        sqlite_timeout=int(os.environ.get("SQLITE_TIMEOUT", "30")),
        db_pool_size=int(os.environ.get("DB_POOL_SIZE", "40")),
        db_max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "20")),
        db_pool_pre_ping=os.environ.get("DB_POOL_PRE_PING", "true").lower() == "true",
    )
