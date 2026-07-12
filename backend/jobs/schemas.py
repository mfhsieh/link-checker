"""任務相關的 Pydantic 模型與 FastAPI 依賴注入類別。

此模組定義了任務建立、查詢、分頁與匯出等操作的驗證 schema、依賴注入參數類別以及內部資料傳輸物件。
"""

from dataclasses import dataclass

from fastapi import (
    Depends,
    Query,
)
from pydantic import BaseModel, EmailStr, Field, field_validator

from crawler.config_utils import validate_domain_delays, validate_ignore_regexes


class CreateJobRequest(BaseModel):
    """建立任務請求的 Schema。

    Attributes:
        start_url (str): 起始爬取的完整網址。
        target_domains (list[str]): 目標爬取網域清單。
        trusted_domains (list[str]): 受信任的外部網域清單。
        ignore_extensions (list[str]): 欲忽略的檔案副檔名清單。
        ignore_regexes (list[str]): 欲忽略的網址正則表達式清單。
        max_depth (int | None): 最大爬取深度。
        max_pages (int | None): 最大爬取頁數。
        delay (float | None): 每次請求的固定延遲時間（秒）。
        timeout (int | None): 請求超時時間（秒）。
        connect_timeout (float | None): 連線超時時間（秒）。
        external_check_timeout (float | None): 外部連結檢查之超時時間（秒）。
        retries (int | None): 重試次數。
        proxy_url (str | None): 代理伺服器網址。
        user_agent (str | None): 自訂 User-Agent。
        ssl_exempt_domains (list[str]): 豁免 SSL 憑證檢查的網域清單。
        social_domains (list[str]): 視為社群媒體平台的網域清單。
        domain_delays (dict[str, float] | None): 特定網域的自訂延遲時間。
    """

    model_config = {"extra": "forbid"}

    start_url: str
    target_domains: list[str]
    trusted_domains: list[str] = []
    ignore_extensions: list[str] = []
    ignore_regexes: list[str] = []
    max_depth: int | None = Field(None, ge=1)
    max_pages: int | None = Field(None, ge=1)
    delay: float | None = Field(None, ge=0.0)
    timeout: int | None = Field(None, ge=1)
    connect_timeout: float | None = Field(None, ge=1.0)
    external_check_timeout: float | None = Field(None, ge=1.0)
    retries: int | None = Field(None, ge=0)
    proxy_url: str | None = None
    user_agent: str | None = None
    ssl_exempt_domains: list[str] = []
    social_domains: list[str] = []
    domain_delays: dict[str, float] | None = None

    @field_validator("start_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """驗證 URL 格式。

        Args:
            v (str): 原始網址字串。

        Returns:
            str: 驗證後的網址字串。

        Raises:
            ValueError: 若網址不以 http:// 或 https:// 開頭時拋出。
        """
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("起始 URL 必須以 http:// 或 https:// 開頭。")
        return v

    @field_validator("target_domains")
    @classmethod
    def validate_domains(cls, v: list[str]) -> list[str]:
        """確保至少有一個目標網域。

        Args:
            v (list[str]): 原始網域列表。

        Returns:
            list[str]: 驗證後的網域列表。

        Raises:
            ValueError: 若列表為空時拋出。
        """
        cleaned = [d.strip() for d in v if d.strip()]
        if not cleaned:
            raise ValueError("至少需要指定一個目標網域。")
        return cleaned

    @field_validator("trusted_domains", "ssl_exempt_domains", "social_domains", "ignore_extensions")
    @classmethod
    def clean_string_lists(cls, v: list[str]) -> list[str]:
        """移除清單中的前後空白與空字串。

        Args:
            v (list[str]): 原始字串列表。

        Returns:
            list[str]: 清理後的字串列表。
        """
        return [item.strip() for item in v if item.strip()]

    @field_validator("ignore_regexes")
    @classmethod
    def validate_regexes(cls, v: list[str]) -> list[str]:
        """驗證正則表達式列表是否合法。

        Args:
            v (list[str]): 欲驗證的正則表達式列表。

        Returns:
            list[str]: 驗證後的正則表達式列表。

        Raises:
            ValueError: 若有任何正則表達式編譯失敗時拋出。
        """
        return validate_ignore_regexes(v) or []

    @field_validator("domain_delays")
    @classmethod
    def validate_domain_delays(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        """驗證特定網域延遲時間是否合法。

        Args:
            v (dict[str, float] | None): 欲驗證的網域延遲時間字典。

        Returns:
            dict[str, float] | None: 驗證後的網域延遲時間字典。

        Raises:
            ValueError: 若有任何延遲時間小於 0 時拋出。
        """
        return validate_domain_delays(v)


class TransferJobRequest(BaseModel):
    """移交任務請求的 Schema。

    Attributes:
        target_email (EmailStr): 移交目標使用者的 Email 信箱。
    """

    model_config = {"extra": "forbid"}

    target_email: EmailStr

    @field_validator("target_email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """將信箱轉為小寫去空白。

        Args:
            v (str): 原始信箱字串。

        Returns:
            str: 格式化後的信箱字串。
        """
        return v.strip().lower()


class PaginationArgs:  # pylint: disable=too-few-public-methods
    """分頁查詢參數。

    Attributes:
        page (int): 頁碼。
        page_size (int): 每頁筆數。
    """

    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ) -> None:
        """初始化分頁查詢參數。

        Args:
            page (int): 頁碼。
            page_size (int): 每頁筆數。
        """
        self.page = page
        self.page_size = page_size


class ResultsFilterArgs:  # pylint: disable=too-few-public-methods
    """任務結果篩選參數。

    Attributes:
        status_filter (str | None): 對應資料庫 status_category 欄位的篩選條件。
        search (str | None): 搜尋關鍵字。
        exclude (str | None): 要排除的目標網域。
        group_by (str): 聚合方式。
        sort_by (str | None): 排序欄位。
        sort_asc (bool): 是否為升冪排序。
        col_filters (str | None): 特定欄位過濾條件 (JSON 格式)。
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        status_filter: str | None = Query(
            None,
            alias="filter",
            pattern="^(dead|broken|not_found|server_error|connection_error|other_error|blocked|insecure|healthy|all)$",
        ),
        search: str | None = Query(None),
        exclude: str | None = Query(None, description="排除指定的目標網域（多個以逗號分隔）"),
        group_by: str = Query("none", pattern="^(none|target|source|domain)$"),
        sort_by: str | None = Query(None),
        sort_asc: bool = Query(True),
        col_filters: str | None = Query(None),
    ) -> None:
        """初始化任務結果篩選參數。

        Args:
            status_filter (str | None): 對應資料庫 status_category 欄位的篩選條件。
            search (str | None): 搜尋關鍵字。
            exclude (str | None): 要排除的目標網域。
            group_by (str): 聚合方式。
            sort_by (str | None): 排序依據的欄位。
            sort_asc (bool): 是否升冪排序。
            col_filters (str | None): 特定欄位的過濾條件 (JSON 格式)。
        """
        self.status_filter = status_filter
        self.search = search
        self.exclude = exclude
        self.group_by = group_by
        self.sort_by = sort_by
        self.sort_asc = sort_asc
        self.col_filters = col_filters


class ResultsQueryArgs:  # pylint: disable=too-few-public-methods, too-many-instance-attributes
    """任務結果查詢參數。

    Attributes:
        status_filter (str | None): 對應資料庫 status_category 欄位的篩選條件。
        search (str | None): 搜尋關鍵字。
        exclude (str | None): 要排除的目標網域。
        group_by (str): 聚合方式。
        page (int): 頁碼。
        page_size (int): 每頁筆數。
        sort_by (str | None): 排序依據的欄位。
        sort_asc (bool): 是否升冪排序。
        col_filters (str | None): 特定欄位的過濾條件 (JSON 格式)。
    """

    def __init__(
        self,
        filters: ResultsFilterArgs = Depends(),
        pagination: PaginationArgs = Depends(),
    ) -> None:
        """初始化結果查詢參數。

        Args:
            filters (ResultsFilterArgs): 篩選與分組參數。
            pagination (PaginationArgs): 分頁參數.
        """
        self.status_filter = filters.status_filter
        self.search = filters.search
        self.exclude = filters.exclude
        self.group_by = filters.group_by
        self.page = pagination.page
        self.page_size = pagination.page_size
        self.sort_by = filters.sort_by
        self.sort_asc = filters.sort_asc
        self.col_filters = filters.col_filters


class ExportQueryArgs:  # pylint: disable=too-few-public-methods
    """匯出結果查詢參數。

    Attributes:
        status_filter (str | None): 對應資料庫 status_category 欄位的篩選條件。
        exclude (str | None): 要排除的網域。
        group_by (str): 聚合方式。
        fmt (str): 輸出格式。
    """

    def __init__(
        self,
        status_filter: str | None = Query(
            None,
            alias="filter",
            pattern="^(dead|broken|not_found|server_error|connection_error|other_error|blocked|insecure|healthy|all)$",
        ),
        exclude: str | None = Query(None),
        group_by: str = Query("none", pattern="^(none|target|source|domain)$"),
        fmt: str = Query("csv", pattern="^(csv|json)$"),
    ) -> None:
        """初始化匯出查詢參數。

        Args:
            status_filter (str | None): 對應資料庫 status_category 欄位的篩選條件。
            exclude (str | None): 要排除的網域。
            group_by (str): 聚合方式。
            fmt (str): 輸出格式 (csv 或 json)。
        """
        self.status_filter = status_filter
        self.exclude = exclude
        self.group_by = group_by
        self.fmt = fmt


@dataclass
class JobCreateConfig:
    """建立任務的設定封裝。

    Attributes:
        start_url (str): 起始爬取的完整網址。
        target_domains (list[str]): 目標爬取網域清單。
        trusted_domains (list[str]): 受信任的外部網域清單。
        crawler_config (dict[str, object]): 爬蟲的詳細設定字典。
    """

    start_url: str
    target_domains: list[str]
    trusted_domains: list[str]
    crawler_config: dict[str, object]


@dataclass
class JobResultQuery:  # pylint: disable=too-many-instance-attributes
    """查詢任務結果的參數封裝。

    Attributes:
        job_id (str): 任務 ID。
        user_id (str): 使用者 ID。
        status_filter (str | None): 對應資料庫 status_category 欄位的篩選條件。
        search (str | None): 搜尋關鍵字。
        exclude (str | None): 欲排除的目標網域。
        group_by (str): 聚合分組方式。
        page (int): 頁碼。
        page_size (int): 每頁筆數。
        sort_by (str | None): 排序欄位。
        sort_asc (bool): 是否使用升冪排序。
        col_filters (str | None): 特定欄位的過濾條件。
    """

    job_id: str
    user_id: str
    status_filter: str | None = None
    search: str | None = None
    exclude: str | None = None
    group_by: str = "none"
    page: int = 1
    page_size: int = 50
    sort_by: str | None = None
    sort_asc: bool = True
    col_filters: str | None = None

    @classmethod
    def from_query_args(cls, job_id: str, user_id: str, query_args: object) -> "JobResultQuery":
        """從查詢參數建立。

        Args:
            job_id (str): 任務 ID。
            user_id (str): 使用者 ID。
            query_args (object): FastAPI 接收到的查詢參數物件。

        Returns:
            JobResultQuery: 建立的查詢封裝物件。
        """
        valid_keys = cls.__annotations__.keys()
        filtered_kwargs = {k: v for k, v in vars(query_args).items() if k in valid_keys}
        return cls(job_id=job_id, user_id=user_id, **filtered_kwargs)


class JobProgress(BaseModel):
    """任務進度統計的 Schema。

    Attributes:
        total (int): 佇列中的總頁面數。
        completed (int): 已完成爬取的頁面數。
        warning (int): 爬取時發生警告的頁面數。
        skipped (int): 被跳過的頁面數。
        pending (int): 等待爬取的頁面數。
        failed (int): 爬取失敗的頁面數。
    """

    total: int
    completed: int
    warning: int
    skipped: int
    pending: int
    failed: int


class JobConfigSnapshot(BaseModel):
    """任務設定快照的 Schema。

    Attributes:
        target_domains (list[str]): 目標爬取網域清單。
        trusted_domains (list[str]): 受信任的外部網域清單。
    """

    model_config = {"extra": "allow"}
    target_domains: list[str]
    trusted_domains: list[str]


class JobDetailResponse(BaseModel):
    """任務詳情 API 回應的 Schema。

    Attributes:
        id (str): 任務 ID。
        start_url (str): 起始網址。
        status (str): 任務狀態。
        created_at (str): 建立時間（ISO 格式）。
        updated_at (str): 更新時間（ISO 格式）。
        config (JobConfigSnapshot): 任務設定快照。
        progress (JobProgress): 任務進度統計。
        external_link_count (int): 發現的外部連結總數。
        is_running (bool): 任務子進程是否運行中。
    """

    id: str
    start_url: str
    status: str
    created_at: str
    updated_at: str
    config: JobConfigSnapshot
    progress: JobProgress
    external_link_count: int
    is_running: bool


@dataclass
class InternalResultQuery:  # pylint: disable=too-many-instance-attributes
    """查詢內部失效結果的參數封裝。

    Attributes:
        job_id (str): 任務 ID。
        user_id (str): 使用者 ID。
        status_filter (str | None): 對應資料庫 status_category 欄位的篩選條件。
        group_by (str): 聚合分組方式。
        page (int): 頁碼。
        page_size (int): 每頁筆數。
        truncate_lists (bool): 是否截斷結果列表。
        sort_by (str | None): 排序欄位。
        sort_asc (bool): 是否使用升冪排序。
        col_filters (str | None): 特定欄位的過濾條件。
    """

    job_id: str
    user_id: str
    status_filter: str | None = None
    group_by: str = "none"
    page: int = 1
    page_size: int = 50
    truncate_lists: bool = True
    sort_by: str | None = None
    sort_asc: bool = True
    col_filters: str | None = None


class ReprobeRequest(BaseModel):
    """局部重新探測請求的 Schema。

    Attributes:
        link_type (Literal["internal", "external"]): 欲探測的連結類型。
        group_by (str): 分組模式。
        urls (list[str]): 欲重新探測的網址清單。
    """

    model_config = {"extra": "forbid"}
    link_type: str = Field(..., pattern="^(internal|external)$")
    group_by: str = "none"
    urls: list[str]


class PartialExportRequest(BaseModel):
    """局部匯出請求的 Schema。

    Attributes:
        link_type (Literal["internal", "external"]): 欲匯出的連結類型。
        group_by (str): 分組模式。
        urls (list[str]): 欲匯出的網址清單。
    """

    model_config = {"extra": "forbid"}
    link_type: str = Field(..., pattern="^(internal|external)$")
    group_by: str = "none"
    urls: list[str]
