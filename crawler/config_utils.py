"""
爬蟲設定與全域設定合併工具模組。
"""

import logging
import os
import re

logger: logging.Logger = logging.getLogger(__name__)


def validate_ignore_regexes(regexes: list[str] | None) -> list[str] | None:
    """
    驗證正則表達式列表是否合法。

    Args:
        regexes (list[str] | None): 原始的正則表達式字串列表。

    Returns:
        list[str] | None: 去除空白後的正則表達式列表，若輸入為 None 則回傳 None。
    """
    if regexes is not None:
        cleaned = [pattern.strip() for pattern in regexes if pattern.strip()]
        for pattern in cleaned:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"無效的正則表達式 '{pattern}': {e}") from e
        return cleaned
    return regexes


def validate_domain_delays(delays: dict[str, float] | None) -> dict[str, float] | None:
    """
    驗證網域延遲時間是否合法。

    Args:
        delays (dict[str, float] | None): 網域對應的延遲時間字典。

    Returns:
        dict[str, float] | None: 驗證後的延遲時間字典，若輸入為 None 則回傳 None。
    """
    if delays is not None:
        for domain, delay in delays.items():
            if delay < 0:
                raise ValueError(f"網域 {domain} 的延遲時間不可小於 0")
    return delays


DEFAULT_GLOBAL_CONFIG: dict[str, object] = {
    "crawler": {
        "min_timeout": 10,
        "max_timeout": 60,
        "min_connect_timeout": 1.0,
        "max_connect_timeout": 30.0,
        "min_external_check_timeout": 1.0,
        "max_external_check_timeout": 30.0,
        "min_delay": 1.0,
        "max_delay": 10.0,
        "min_retries": 0,
        "max_retries": 5,
        "max_max_depth": None,
        "max_max_pages": None,
        "max_content_length": 10485760,
        "max_redirects": 10,
        "jitter_ratio": 0.2,
        "user_agent": None,
        "proxy_url": None,
        "timeout": 30,
        "connect_timeout": 5.0,
        "external_check_timeout": 10.0,
        "delay": 3.0,
        "retries": 3,
        "max_depth": None,
        "max_pages": None,
        "mime_type_filter": {"enabled": True, "allowed_types": ["text/html", "application/xhtml+xml"]},
        "ignore_regexes": [],
        "domain_delays": {},
        "ssl_exempt_domains": [],
        "social_domains": [
            "facebook.com",
            "fb.com",
            "youtube.com",
            "youtu.be",
            "instagram.com",
            "twitter.com",
            "linkedin.com",
            "line.me",
        ],
        "ignore_extensions": (
            ".pdf .doc .docx .xls .xlsx .ppt .pptx .odt .ods .odp .csv .txt .rtf .epub .mobi "
            ".jpg .jpeg .png .gif .svg .webp .bmp .ico .tif .tiff .psd .ai .eps .mp4 .mp3 .avi "
            ".mov .wmv .flv .mkv .webm .ogg .wav .m4a .aac .zip .rar .tar .gz .7z .bz2 .xz .iso "
            ".dmg .pkg .deb .rpm .css .js .json .xml .exe .apk .bin .woff .woff2 .ttf .eot .otf "
            ".dll .so .class .jar"
        ).split(),
    },
}

ALLOWED_CRAWLER_KEYS: set[str] = {
    "user_agent",
    "proxy_url",
    "timeout",
    "connect_timeout",
    "external_check_timeout",
    "delay",
    "retries",
    "max_depth",
    "max_pages",
    "mime_type_filter",
    "ignore_regexes",
    "domain_delays",
    "ssl_exempt_domains",
    "social_domains",
    "ignore_extensions",
}


def _sanitize_numeric_type(k: str, v: object, exp: type | tuple[type, ...], config: dict[str, object]) -> None:
    """處理數值型別的設定值清理。

    Args:
        k (str): 設定的鍵名。
        v (object): 設定的原始值。
        exp (type | tuple[type, ...]): 預期的型別。
        config (dict[str, object]): 爬蟲設定字典，清理後會直接修改此字典。

    Returns:
        None
    """
    # 在 Python 中 bool 是 int 的子類別，需特別防堵
    if isinstance(v, bool):
        logging.warning("設定 '%s' 不應為布林值，將被忽略。", k)
        config[k] = None
    elif not isinstance(v, exp):
        try:
            config[k] = float(v) if exp == (int, float) else int(v)
        except (ValueError, TypeError):
            logging.warning("設定 '%s' 無法轉換為數字，將被忽略。", k)
            config[k] = None


def _sanitize_string_type(k: str, v: object, config: dict[str, object]) -> None:
    """處理字串型別的設定值清理。

    Args:
        k (str): 設定的鍵名。
        v (object): 設定的原始值。
        config (dict[str, object]): 爬蟲設定字典。

    Returns:
        None
    """
    if not isinstance(v, str):
        config[k] = str(v)


def _sanitize_domain_delays(k: str, v: dict, config: dict[str, object]) -> None:
    """清理 domain_delays 字典。

    Args:
        k (str): 設定的鍵名。
        v (dict): 原始的 domain_delays 字典。
        config (dict[str, object]): 爬蟲設定字典。

    Returns:
        None
    """
    sanitized_dd = {}
    for dd_k, dd_v in v.items():
        try:
            val = float(dd_v)
            if val >= 0:
                sanitized_dd[str(dd_k)] = val
            else:
                logging.warning("設定 'domain_delays' 的值不能為負數，已略過: %s", dd_v)
        except (ValueError, TypeError):
            logging.warning("設定 'domain_delays' 含有無效值，已略過: %s", dd_v)
    config[k] = sanitized_dd


def _sanitize_mime_type_filter(v: dict) -> None:
    """清理 mime_type_filter 字典（就地修改）。

    Args:
        v (dict): mime_type_filter 字典。

    Returns:
        None
    """
    if "enabled" in v and isinstance(v["enabled"], str):
        v["enabled"] = v["enabled"].lower() in ("true", "1", "yes", "on")
    if "allowed_types" in v:
        if isinstance(v["allowed_types"], str):
            v["allowed_types"] = [v["allowed_types"]]
        elif not isinstance(v["allowed_types"], list):
            v["allowed_types"] = ["text/html", "application/xhtml+xml"]
        else:
            v["allowed_types"] = [str(x) for x in v["allowed_types"]]


def _sanitize_dict_type(k: str, v: object, config: dict[str, object]) -> None:
    """處理字典型別的設定值清理。

    Args:
        k (str): 設定的鍵名。
        v (object): 設定的原始值。
        config (dict[str, object]): 爬蟲設定字典。

    Returns:
        None
    """
    if not isinstance(v, dict):
        logging.warning("設定 '%s' 必須為字典 (Key-Value) 格式，將被忽略。", k)
        config[k] = None
    elif k == "domain_delays":
        _sanitize_domain_delays(k, v, config)
    elif k == "mime_type_filter":
        _sanitize_mime_type_filter(v)


def _sanitize_list_type(k: str, v: object, config: dict[str, object]) -> None:
    """處理陣列清單型別的設定值清理。

    Args:
        k (str): 設定的鍵名。
        v (object): 設定的原始值。
        config (dict[str, object]): 爬蟲設定字典。

    Returns:
        None
    """
    if isinstance(v, str):
        config[k] = [v]
    elif not isinstance(v, list):
        try:
            config[k] = list(v)
        except TypeError:
            logging.warning("設定 '%s' 必須為陣列清單格式，將被忽略。", k)
            config[k] = []


def _sanitize_crawler_types(config: dict[str, object]) -> None:
    """
    強制檢查並修正設定檔中的資料型別，防範因 YAML 手動填寫錯誤所導致的系統崩潰。

    此函式會就地 (in-place) 修改傳入的設定字典，針對以下四類資料型別進行容錯與轉換：
    1. 數值類 (Numeric)：將字串格式的數字主動轉回 int 或 float。特別防堵 bool 型別混充為數字。若無法轉換，將設為 None。
    2. 字串類 (String)：若非字串型態，強制轉為字串。
    3. 字典類 (Dict)：若非字典型態，直接抹除設為 None。
    4. 陣列清單類 (List)：若為單一字串則自動包裝為單元素陣列；若完全無法轉換為 list，則設為空陣列 []。

    經此處理後，無效或不合法的設定會被安全地丟棄，以確保後續合併邏輯能順利退回使用系統的安全預設值。

    Args:
        config (dict[str, object]): 需要進行型別檢查與清理的爬蟲設定字典。

    Returns:
        None
    """
    numeric_types = {
        "timeout": (int, float),
        "connect_timeout": (int, float),
        "external_check_timeout": (int, float),
        "delay": (int, float),
        "retries": int,
        "max_depth": int,
        "max_pages": int,
        "min_timeout": (int, float),
        "max_timeout": (int, float),
        "min_connect_timeout": (int, float),
        "max_connect_timeout": (int, float),
        "min_external_check_timeout": (int, float),
        "max_external_check_timeout": (int, float),
        "min_delay": (int, float),
        "max_delay": (int, float),
        "min_retries": int,
        "max_retries": int,
        "max_max_depth": int,
        "max_max_pages": int,
        "max_content_length": int,
        "max_redirects": int,
        "jitter_ratio": (int, float),
    }
    string_types = {"user_agent", "proxy_url"}
    dict_types = {"mime_type_filter", "domain_delays"}
    list_types = {"ignore_extensions", "ignore_regexes", "ssl_exempt_domains", "social_domains"}

    for k, v in list(config.items()):
        if v is None:
            continue

        if k in numeric_types:
            _sanitize_numeric_type(k, v, numeric_types[k], config)
        elif k in string_types:
            _sanitize_string_type(k, v, config)
        elif k in dict_types:
            _sanitize_dict_type(k, v, config)
        elif k in list_types:
            _sanitize_list_type(k, v, config)


def _apply_crawler_defaults(crawler_config: dict[str, object], global_crawler_config: dict[str, object]) -> None:
    """
    套用全域預設值到 crawler_config 中。

    依據不同參數的特性，分為兩種處理邏輯：
    1. 不允許為 None 的欄位 (若設為 None 視同未設定，將強制覆寫為預設值)：
       - 數值與時間限制：timeout, connect_timeout, external_check_timeout, delay, retries
       - 功能開關與標頭：user_agent, mime_type_filter
    2. 允許為 None 的欄位 (None 具備「無限制」或「不使用」之特殊意義，僅在完全缺漏鍵值時才補上預設值)：
       - 資源探索限制：max_depth, max_pages
       - 功能開關與標頭：proxy_url
    3. 不在此套用預設值，交由後續聯集合併邏輯處理的欄位：
       - 陣列與字典：ignore_extensions, ignore_regexes, ssl_exempt_domains, social_domains, domain_delays

    Args:
        crawler_config (dict[str, object]): 個別任務的爬蟲設定。
        global_crawler_config (dict[str, object]): 全域爬蟲預設設定。

    Returns:
        None
    """
    default_crawler = DEFAULT_GLOBAL_CONFIG.get("crawler")
    if not isinstance(default_crawler, dict):
        default_crawler = {}

    # 1. 不允許為 None 的欄位 (若為 None 視同未設定，強制套用預設值)
    non_nullable_keys = [
        "timeout",
        "connect_timeout",
        "external_check_timeout",
        "delay",
        "retries",
        "user_agent",
        "mime_type_filter",
        "max_content_length",
        "max_redirects",
        "jitter_ratio",
    ]
    for key in non_nullable_keys:
        if crawler_config.get(key) is None:
            g_val = global_crawler_config.get(key)
            crawler_config[key] = g_val if g_val is not None else default_crawler.get(key)

    # 2. 允許為 None 的欄位 (None 具備特殊意義，例如無限制或不使用，僅在完全未提供鍵值時才填補)
    nullable_keys = [
        "max_depth",
        "max_pages",
        "proxy_url",
    ]
    for key in nullable_keys:
        if key not in crawler_config:
            crawler_config[key] = global_crawler_config.get(key, default_crawler.get(key))


def _merge_crawler_lists(crawler_config: dict[str, object], global_crawler_config: dict[str, object]) -> None:
    """
    聯集合併個別任務與全域設定中的清單 (List) 與字典 (Dict) 參數。

    基於資安防護與資源限制的疊加原則，此類設定採取「聯集 (Union)」與「合併」而非「覆寫」：
    1. 陣列聯集：針對 ignore_extensions, ignore_regexes, ssl_exempt_domains, social_domains，
       將全域與個別設定的項目進行合併並去重，確保全域安全規則不被意外洗掉。
    2. 資料正規化 (Sanitization)：
       - 若傳入單一字串，會自動包裝為陣列。
       - ignore_extensions：自動去除多餘空白、轉小寫，並確保開頭具備小數點 ('.')。
       - ssl_exempt_domains, social_domains：自動去除多餘空白並轉小寫。
    3. 字典合併：針對 domain_delays，合併兩者的設定，若網域重複則以個別任務的設定優先覆寫。

    此操作會就地 (in-place) 修改 crawler_config。

    Args:
        crawler_config (dict[str, object]): 個別任務的爬蟲設定。
        global_crawler_config (dict[str, object]): 全域爬蟲預設設定。

    Returns:
        None
    """
    list_keys = [
        "ignore_extensions",
        "ignore_regexes",
        "ssl_exempt_domains",
        "social_domains",
    ]
    for key in list_keys:
        g_list: list[str] = global_crawler_config.get(key) or []
        l_list: list[str] = crawler_config.get(key) or []

        if isinstance(g_list, str):
            g_list = [g_list]
        if isinstance(l_list, str):
            l_list = [l_list]

        if key == "ignore_extensions":
            g_exts = [str(e).strip().lower() for e in g_list if str(e).strip()]
            g_list = [e if e.startswith(".") else f".{e}" for e in g_exts]
            l_exts = [str(e).strip().lower() for e in l_list if str(e).strip()]
            l_list = [e if e.startswith(".") else f".{e}" for e in l_exts]
        elif key in ("ssl_exempt_domains", "social_domains"):
            g_list = [str(d).strip().lower() for d in g_list if str(d).strip()]
            l_list = [str(d).strip().lower() for d in l_list if str(d).strip()]
        elif key == "ignore_regexes":
            g_list = [str(r).strip() for r in g_list if str(r).strip()]
            l_list = [str(r).strip() for r in l_list if str(r).strip()]

        if g_list or l_list:
            crawler_config[key] = list(set(g_list + l_list))
        elif key in ["ssl_exempt_domains", "social_domains"]:
            crawler_config[key] = []

    global_domain_delays: dict[str, object] = global_crawler_config.get("domain_delays") or {}
    local_domain_delays: dict[str, object] = crawler_config.get("domain_delays") or {}
    crawler_config["domain_delays"] = {**global_domain_delays, **local_domain_delays}


def _enforce_crawler_limits(crawler_config: dict[str, object], global_crawler_config: dict[str, object]) -> None:
    """
    強制套用全域上下限。

    Args:
        crawler_config (dict[str, object]): 個別任務的爬蟲設定。
        global_crawler_config (dict[str, object]): 全域爬蟲限制設定。

    Returns:
        None
    """
    default_crawler = DEFAULT_GLOBAL_CONFIG.get("crawler")
    if not isinstance(default_crawler, dict):
        default_crawler = {}

    def _clamp_numeric_limit(key: str, min_k: str, max_k: str, def_min: float | int, def_max: float | int) -> None:
        """套用數值型別的上下限。

        Args:
            key (str): 設定鍵名。
            min_k (str): 最小值的全域設定鍵名。
            max_k (str): 最大值的全域設定鍵名。
            def_min (float | int): 預設的最小值。
            def_max (float | int): 預設的最大值。

        Returns:
            None
        """
        min_val = global_crawler_config.get(min_k)
        if min_val is None:
            min_val = default_crawler.get(min_k, def_min)
        if min_val is None:
            min_val = def_min

        max_val = global_crawler_config.get(max_k)
        if max_val is None:
            max_val = default_crawler.get(max_k, def_max)
        if max_val is None:
            max_val = def_max

        val = crawler_config.get(key)
        if val is None:
            return

        if val < min_val:
            logging.warning("個別設定的 %s (%s) 小於最小值 (%s)，強制套用。", key, val, min_val)
            crawler_config[key] = min_val
        elif val > max_val:
            logging.warning("個別設定的 %s (%s) 大於最大值 (%s)，強制套用。", key, val, max_val)
            crawler_config[key] = max_val

    def _clamp_optional_limit(key: str, max_k: str, def_max: int) -> None:
        """套用可為 None 的選項上限限制。

        Args:
            key (str): 設定鍵名。
            max_k (str): 最大值的全域設定鍵名。
            def_max (int): 預設的最大值。

        Returns:
            None
        """
        if max_k in global_crawler_config:
            max_val = global_crawler_config[max_k]
        else:
            max_val = default_crawler.get(max_k, def_max)
            if max_val is None:
                max_val = def_max

        val = crawler_config.get(key)

        if val is None:
            # 若為無限制，但全域有設定最大值限制，則強制套用最大值
            if max_val is not None:
                logging.warning("個別設定的 %s 為無限制，但全域最大限制為 %s，強制套用。", key, max_val)
                crawler_config[key] = max_val
        else:
            if val < 1:
                logging.warning("個別設定的 %s (%s) 小於最小值 1，強制套用 1。", key, val)
                crawler_config[key] = 1
            elif max_val is not None and val > max_val:
                logging.warning("個別設定的 %s (%s) 大於最大值 (%s)，強制套用。", key, val, max_val)
                crawler_config[key] = max_val

    limits: list[tuple[str, str, str, float | int, float | int]] = [
        ("timeout", "min_timeout", "max_timeout", 10, 60),
        ("connect_timeout", "min_connect_timeout", "max_connect_timeout", 1.0, 30.0),
        ("external_check_timeout", "min_external_check_timeout", "max_external_check_timeout", 1.0, 30.0),
        ("delay", "min_delay", "max_delay", 1.0, 10.0),
        ("retries", "min_retries", "max_retries", 0, 5),
    ]

    for key, min_k, max_k, def_min, def_max in limits:
        _clamp_numeric_limit(key, min_k, max_k, def_min, def_max)

    # 針對可為 None (無限制) 的 max_depth 與 max_pages 進行特殊處理
    optional_limits = [
        ("max_depth", "max_max_depth", 10),
        ("max_pages", "max_max_pages", 10000),
    ]
    for opt_key, opt_max_k, opt_def_max in optional_limits:
        _clamp_optional_limit(opt_key, opt_max_k, opt_def_max)


def merge_and_validate_crawler_config(config: dict[str, object], global_config: dict[str, object]) -> dict[str, object]:
    """
    合併全域與個別任務的爬蟲設定，並確保個別設定符合白名單與安全上下限。

    此函式處理了配置合併的完整生命週期，執行步驟如下：
    1. 依據 ALLOWED_CRAWLER_KEYS 白名單過濾個別任務不允許設定的參數。
    2. 將缺失的設定值補上全域預設值 (_apply_crawler_defaults)。
    3. 對於清單類型的設定（如忽略副檔名、豁免網域）進行聯集合併 (_merge_crawler_lists)。
    4. 載入並優先套用系統環境變數的覆寫 (例如 Proxy 密碼與額外豁免網域)。
    5. 強制檢查並收斂所有數值參數，使其不超出全域配置的安全上下限 (_enforce_crawler_limits)。

    Args:
        config (dict[str, object]): 個別任務請求的原始設定 (通常來自 API 或 YAML)。
        global_config (dict[str, object]): 系統全域配置 (通常從 config_global.yaml 讀取)。

    Returns:
        dict[str, object]: 經過過濾、合併與驗證後的最終爬蟲設定，可直接寫入資料庫並供 CrawlerCore 建立使用。
    """
    # 1. 取得個別任務的 crawler 區塊設定，並過濾掉不在白名單內的非法或敏感欄位
    crawler_config: dict[str, object] = config.get("crawler", {})
    for key in list(crawler_config.keys()):
        if key not in ALLOWED_CRAWLER_KEYS:
            logging.warning("個別設定 config.yaml 不允許覆寫 crawler.%s，此設定將被忽略。", key)
            del crawler_config[key]

    # 2. 取得全域的 crawler 區塊設定
    global_crawler_config: dict[str, object] = global_config.get("crawler", {})

    # 3. 進行型別容錯與防呆轉換，避免手寫 YAML 造成系統崩潰
    _sanitize_crawler_types(crawler_config)
    _sanitize_crawler_types(global_crawler_config)

    # 4. 填補預設值
    _apply_crawler_defaults(crawler_config, global_crawler_config)
    # 5. 聯集合併清單類型的參數與字典
    _merge_crawler_lists(crawler_config, global_crawler_config)

    # 6. 環境變數優先覆寫 (處理如 Proxy 密碼等不宜寫入檔案的機密設定)
    env_proxy = os.environ.get("CRAWLER_PROXY_URL")
    if env_proxy:
        crawler_config["proxy_url"] = env_proxy

    # 環境變數的自簽憑證豁免網域：將環境變數設定與先前的結果再進行一次聯集合併
    env_ssl_exempt = os.environ.get("CRAWLER_SSL_EXEMPT_DOMAINS")
    if env_ssl_exempt:
        crawler_config["ssl_exempt_domains"] = list(
            set(
                crawler_config.get("ssl_exempt_domains", [])
                + [d.strip() for d in env_ssl_exempt.split(",") if d.strip()]
            )
        )

    # 7. 強制執行防呆檢查，確保各項數值落在全域安全上下限之內
    _enforce_crawler_limits(crawler_config, global_crawler_config)

    return crawler_config
