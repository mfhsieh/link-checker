"""
外部連結檢查爬蟲的命令列介面 (CLI)。

此腳本負責解析命令列參數、讀取 YAML 設定檔，
並透過 JobManager 啟動全新的任務或是恢復先前中斷的任務。
"""

import argparse
import json
import logging
import os
import re
import sys
import secrets
import string
from typing import Any
import yaml
from crawler.manager import JobManager

# 設定初始的 logging，只輸出到畫面，確保 setup_logging 呼叫前的錯誤能被顯示
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def load_config(
    config_path: str, allowed_directory: str | None = None
) -> dict[str, Any]:
    """
    從指定的 YAML 檔案讀取設定值。

    Args:
        config_path (str): YAML 設定檔的檔案路徑。
        allowed_directory (str | None): 限制此設定檔只能放置於此目錄（或其子目錄）下。

    Returns:
        dict[str, Any]: 讀取出來的設定字典 (Dictionary) 物件。

    Raises:
        PermissionError: 當設定檔不符合安全路徑限制時拋出。
        FileNotFoundError: 當指定的設定檔路徑不存在時拋出。
        yaml.YAMLError: 當 YAML 檔案格式錯誤無法解析時拋出。
    """
    if allowed_directory is not None:
        abs_allowed_dir = os.path.realpath(allowed_directory)
        abs_config_path = os.path.realpath(config_path)
        try:
            common = os.path.commonpath([abs_allowed_dir, abs_config_path])
            if common != abs_allowed_dir:
                raise PermissionError(
                    f"設定檔 {config_path} 必須位於指定目錄 ({allowed_directory}) 下以符合資安規範"
                )
        except ValueError as exc:
            raise PermissionError("無法比對設定檔路徑與允許目錄的安全路徑。") from exc

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(global_config: dict[str, Any]) -> None:
    """
    依據全域設定檔來套用 Logging 輸出層級與檔案路徑。

    會從全域設定中讀取 `logging` 區塊，分別設定畫面 (Console) 與檔案 (File)
    的輸出層級與日誌檔案路徑。

    Args:
        global_config (dict[str, Any]): 全域設定字典物件，需包含系統的全域設定參數。
    """
    logging_config = global_config.get("logging", {})

    console_level_str = logging_config.get("console_level", "INFO")
    file_level_str = logging_config.get("file_level", "DEBUG")
    log_file = logging_config.get("log_file", "log/crawler.log")

    console_level = getattr(logging, console_level_str.upper(), logging.INFO)
    file_level = getattr(logging, file_level_str.upper(), logging.DEBUG)

    # 確保日誌目錄存在
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    root_logger = logging.getLogger()
    # 將 root logger 的層級設為兩者之中最低的，確保訊息能被轉發給 handler
    root_logger.setLevel(min(console_level, file_level))

    # 清除舊的 handlers
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # 設定 Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 設定 File Handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def generate_random_password(length: int = 16) -> str:
    """
    產生符合安全強度要求的高強度隨機密碼。

    Args:
        length (int): 欲產生的密碼長度，預設為 16 字元。

    Returns:
        str: 隨機產生的高強度密碼字串，包含大小寫英文字母、數字及特殊字元。

    Raises:
        RuntimeError: 若超過最大重試次數仍無法產生符合條件的密碼（理論上不會發生）。
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    max_attempts = 100
    for _ in range(max_attempts):
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and sum(c.isdigit() for c in password) >= 3
        ):
            return password
    raise RuntimeError("無法在合理嘗試次數內產生符合條件的密碼，請檢查 alphabet 設定。")


def create_admin(email: str) -> None:
    """
    建立或重設系統管理員帳號。

    考量到 CLI-First 獨立性原則，此函式內部進行局部引入 (Local Import)
    以避免一般的爬蟲指令載入 Auth DB 相關套件與資料庫連線。

    Args:
        email (str): 欲建立或重設密碼的管理員信箱。

    Raises:
        SystemExit: 當提供的 Email 格式不合法時，終止程式並回傳錯誤碼 1。
    """
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        print(f"錯誤：提供的 Email 格式不合法 ({email})")
        sys.exit(1)

    # pylint: disable=import-outside-toplevel
    from backend.auth.db import get_auth_session_local
    from backend.auth.models import User
    from backend.auth.password import hash_password

    session_local = get_auth_session_local()
    with session_local() as db:
        # 依據 §12.2 規定：確認 Auth DB 尚未存在任何 Admin 帳號
        admin_count = db.query(User).filter(User.role == "admin").count()
        existing = db.query(User).filter(User.email == email).first()

        # 如果系統已經有管理員，且要建立的不是原本那位，則強制阻擋
        if admin_count > 0 and (not existing or existing.role != "admin"):
            print("錯誤：系統中已存在管理員帳號。依據安全規範，後續管理員請透過後台網頁介面邀請，禁止使用 CLI 重複建立。")
            sys.exit(1)

        random_password = generate_random_password()
        if existing:
            print(
                f"使用者 {email} 已存在，將更新其密碼並設為管理員。"
            )
            existing.password_hash = hash_password(random_password)
            existing.role = "admin"
            existing.status = "active"
        else:
            user = User(
                email=email,
                password_hash=hash_password(random_password),
                role="admin",
                status="active",
            )
            db.add(user)
        db.commit()
        print(f"成功設定管理員帳號：{email}")
        print("============================================================")
        print(f"系統產生的初始隨機密碼：{random_password}")
        print("請使用此密碼登入系統，登入後請自行至「修改密碼」設定安全密碼。")
        print("============================================================")


def _is_help_needed(args: argparse.Namespace) -> bool:
    """
    檢查是否未帶入任何主要指令。

    Args:
        args (argparse.Namespace): 解析後的命令列參數物件。

    Returns:
        bool: 如果未包含任何有效的主要指令，則回傳 True；否則回傳 False。
    """
    commands = [
        args.config,
        args.resume is not None,
        args.list_jobs,
        args.report,
        args.export,
        args.pause,
        args.delete,
        args.reset,
        args.create_admin,
        args.serve,
    ]
    return not any(commands)


def parse_args() -> argparse.Namespace | None:
    """
    設定並解析命令列參數。

    若未指定必要的參數 (例如：未帶任何任務相關操作參數)，則會印出命令列使用說明，並回傳 None。

    Returns:
        argparse.Namespace | None: 解析後的參數命名空間物件。若未提供必要參數則回傳 None。
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="外部連結檢查爬蟲 (External Link Checker Crawler)"
    )
    parser.add_argument(
        "-g",
        "--global-config",
        type=str,
        default=os.environ.get("GLOBAL_CONFIG_PATH", "config/config_global.yaml"),
        help="全域 YAML 設定檔的路徑",
    )
    parser.add_argument("-c", "--config", type=str, help="YAML 設定檔的路徑")
    parser.add_argument("-u", "--user-id", type=str, help="(選填) 綁定任務的擁有者 ID")
    parser.add_argument("-r", "--resume", type=str, help="欲恢復執行之任務 (Job) ID")
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="(選填) 強制接管狀態卡在 running 的任務（搭配 --resume 使用）",
    )
    parser.add_argument(
        "--list-jobs", action="store_true", help="列出所有已建立的爬蟲任務"
    )
    parser.add_argument(
        "--pause",
        type=str,
        metavar="JOB_ID",
        help="暫停指定任務 (僅在任務狀態為 running 時生效)",
    )
    parser.add_argument(
        "--delete",
        type=str,
        metavar="JOB_ID",
        help="刪除指定任務，並清理其所有佇列與外連記錄",
    )
    parser.add_argument(
        "--reset",
        type=str,
        metavar="JOB_ID",
        help="重設指定任務，清除已探索外連並將狀態與佇列歸零",
    )
    parser.add_argument("--report", type=str, help="檢視指定任務的詳細進度與統計報表")
    parser.add_argument(
        "--export",
        type=str,
        metavar="JOB_ID",
        help="將指定任務 ID 所找到的外部連結匯出",
    )
    parser.add_argument(
        "--output",
        type=str,
        metavar="FILE_PATH",
        help="(選填) 指定匯出檔案的路徑與名稱，預設為 report/<JOB_ID>.csv (或 .json)",
    )
    parser.add_argument(
        "--filter",
        type=str,
        choices=["dead", "broken", "insecure"],
        help="(選填) 搭配 --export 使用，篩選匯出內容 (dead, broken, insecure)",
    )
    parser.add_argument(
        "--group",
        action="store_true",
        help="(選填) 搭配 --export 使用，按外部目標連結進行去重與聚合導出",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="(選填) 以 JSON 格式輸出或導出結果 (支援 --list-jobs, --report, --export)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="啟動 Web 後端伺服器 (FastAPI / Uvicorn)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="(選填) 搭配 --serve 使用，啟用 Uvicorn 的開發模式熱重載",
    )
    parser.add_argument(
        "--create-admin",
        nargs=1,
        metavar="EMAIL",
        help="建立或更新系統管理員帳號 (隨機產生密碼並設為待設密狀態)",
    )

    args: argparse.Namespace = parser.parse_args()

    if _is_help_needed(args):
        parser.print_help()
        return None

    return args


def _apply_crawler_defaults(
    crawler_config: dict[str, Any], global_crawler_config: dict[str, Any]
) -> None:
    """
    套用全域預設值到 crawler_config 中。

    Args:
        crawler_config (dict[str, Any]): 個別任務的爬蟲設定字典。
        global_crawler_config (dict[str, Any]): 全域系統的爬蟲預設設定字典。
    """
    if "timeout" not in crawler_config:
        crawler_config["timeout"] = global_crawler_config.get("timeout", 30)
    if "delay" not in crawler_config:
        crawler_config["delay"] = global_crawler_config.get("delay", 3.0)
    if "retries" not in crawler_config:
        crawler_config["retries"] = global_crawler_config.get("retries", 3)
    if "mime_type_filter" not in crawler_config:
        crawler_config["mime_type_filter"] = global_crawler_config.get(
            "mime_type_filter",
            {"enabled": True, "allowed_types": ["text/html", "application/xhtml+xml"]},
        )
    if "user_agent" not in crawler_config:
        crawler_config["user_agent"] = global_crawler_config.get(
            "user_agent",
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
    if "max_depth" not in crawler_config:
        crawler_config["max_depth"] = global_crawler_config.get("max_depth", None)
    if "max_pages" not in crawler_config:
        crawler_config["max_pages"] = global_crawler_config.get("max_pages", None)
    if "proxy_url" not in crawler_config:
        crawler_config["proxy_url"] = global_crawler_config.get("proxy_url", None)


def _merge_crawler_lists(
    crawler_config: dict[str, Any], global_crawler_config: dict[str, Any]
) -> None:
    """
    聯集合併 crawler_config 中的 list 參數。

    將全域設定中的清單屬性與個別任務設定中的清單屬性合併，並進行去重處理。

    Args:
        crawler_config (dict[str, Any]): 個別任務的爬蟲設定字典。
        global_crawler_config (dict[str, Any]): 全域系統的爬蟲預設設定字典。
    """
    list_keys = [
        "ignore_extensions",
        "ignore_regexes",
        "ssl_exempt_domains",
    ]
    for key in list_keys:
        g_list: list[str] = global_crawler_config.get(key) or []
        l_list: list[str] = crawler_config.get(key) or []

        if isinstance(g_list, str):
            g_list = [g_list]
        if isinstance(l_list, str):
            l_list = [l_list]

        if g_list or l_list:
            crawler_config[key] = list(set(g_list + l_list))
        elif key in ["ssl_exempt_domains"]:
            crawler_config[key] = []

    global_domain_delays: dict = global_crawler_config.get("domain_delays") or {}
    local_domain_delays: dict = crawler_config.get("domain_delays") or {}
    crawler_config["domain_delays"] = {**global_domain_delays, **local_domain_delays}


def _enforce_crawler_limits(
    crawler_config: dict[str, Any], global_crawler_config: dict[str, Any]
) -> None:
    """
    強制套用全域上下限。

    針對特定的爬蟲設定項目（如逾時時間、延遲、重試次數等），確保其值不會低於
    全域設定的最小值，也不會高於全域設定的最大值。

    Args:
        crawler_config (dict[str, Any]): 個別任務的爬蟲設定字典。
        global_crawler_config (dict[str, Any]): 全域系統的爬蟲預設設定字典。
    """
    limits = [
        ("timeout", "min_timeout", "max_timeout", 30, 120),
        ("delay", "min_delay", "max_delay", 3.0, 6.0),
        ("retries", "min_retries", "max_retries", 0, 5),
    ]
    for key, min_k, max_k, def_min, def_max in limits:
        min_val = global_crawler_config.get(min_k, def_min)
        max_val = global_crawler_config.get(max_k, def_max)
        if crawler_config[key] < min_val:
            logging.warning(
                "個別設定的 %s (%s) 小於最小值 (%s)，強制套用。",
                key,
                crawler_config[key],
                min_val,
            )
            crawler_config[key] = min_val
        elif crawler_config[key] > max_val:
            logging.warning(
                "個別設定的 %s (%s) 大於最大值 (%s)，強制套用。",
                key,
                crawler_config[key],
                max_val,
            )
            crawler_config[key] = max_val


def merge_and_validate_crawler_config(
    config: dict[str, Any], global_config: dict[str, Any]
) -> dict[str, Any]:
    """
    合併全域與個別的爬蟲設定，並確保個別設定遵守全域上下限。

    Args:
        config (dict[str, Any]): 個別任務的完整設定字典。
        global_config (dict[str, Any]): 系統的全域設定字典。

    Returns:
        dict[str, Any]: 經過合併與驗證處理後的爬蟲專屬設定字典。
    """
    crawler_config: dict[str, Any] = config.get("crawler", {})
    allowed_crawler_keys: set[str] = {
        "timeout",
        "delay",
        "retries",
        "mime_type_filter",
        "ignore_extensions",
        "ignore_regexes",
        "user_agent",
        "ssl_exempt_domains",
        "domain_delays",
        "max_depth",
        "max_pages",
        "proxy_url",
    }
    for key in list(crawler_config.keys()):
        if key not in allowed_crawler_keys:
            logging.warning(
                "個別設定 config.yaml 不允許覆寫 crawler.%s，此設定將被忽略。", key
            )
            del crawler_config[key]

    global_crawler_config: dict[str, Any] = global_config.get("crawler", {})

    _apply_crawler_defaults(crawler_config, global_crawler_config)
    _merge_crawler_lists(crawler_config, global_crawler_config)

    env_proxy = os.environ.get("CRAWLER_PROXY_URL")
    if env_proxy:
        crawler_config["proxy_url"] = env_proxy

    env_ssl_exempt = os.environ.get("CRAWLER_SSL_EXEMPT_DOMAINS")
    if env_ssl_exempt:
        crawler_config["ssl_exempt_domains"] = list(
            set(
                crawler_config.get("ssl_exempt_domains", [])
                + [d.strip() for d in env_ssl_exempt.split(",") if d.strip()]
            )
        )

    _enforce_crawler_limits(crawler_config, global_crawler_config)
    return crawler_config


def _handle_list_jobs(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理列出任務的指令。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含 user_id 與 json 等選項。
    """
    jobs = manager.get_all_jobs(user_id=args.user_id)
    if args.json:
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
    else:
        print("\n=== 爬蟲任務列表 ===")
        print(
            f"{'Job ID':<38} | {'User ID':<20} | {'Status':<10} | "
            f"{'Created At':<20} | {'Start URL'}"
        )
        print("-" * 120)
        for j in jobs:
            uid = j.get("user_id") or "N/A"
            print(
                f"{j['id']:<38} | {uid:<20} | {j['status']:<10} | "
                f"{j['created_at']:<20} | {j['start_url']}"
            )
        print("====================\n")


def _handle_report(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理檢視報表的指令。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含報表 ID 與 json 選項。
    """
    report = manager.get_job_report(args.report)
    if not report:
        logging.error("找不到指定的任務 ID: %s", args.report)
        sys.exit(1)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n=== 任務進度報表 ===")
        print(f"任務 ID: {report['id']}")
        print(f"起始網址: {report['start_url']}")
        print(f"當前狀態: {report['status']}")
        print(f"建立時間: {report['created_at']}")
        print(f"最後更新: {report['updated_at']}")
        print("-" * 20)
        print("【佇列進度統計】")
        print(f"  總計網址數: {report['queue']['total']}")
        print(f"  已完成 (Completed): {report['queue']['completed']}")
        print(f"  已略過 (Skipped):   {report['queue']['skipped']}")
        print(f"  等待中 (Pending):   {report['queue']['pending']}")
        print(f"  已失敗 (Failed):    {report['queue']['failed']}")
        print("-" * 20)
        print("【產出成果】")
        print(f"  尋獲外部連結數: {report['external_links']}")
        print("====================\n")


def _handle_export(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理匯出結果的指令。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含匯出目標、篩選與群組等選項。
    """
    ext = ".json" if args.json else ".csv"
    output_path = args.output if args.output else f"report/{args.export}{ext}"
    logging.info("準備將任務 %s 匯出至 %s...", args.export, output_path)
    success = manager.export_job_results(
        args.export, output_path, status_filter=args.filter, export_group=args.group
    )
    if success:
        logging.info("匯出成功！")
    else:
        sys.exit(1)


def _handle_job_management(manager: JobManager, args: argparse.Namespace) -> bool:
    """
    處理不需要讀取 job config 的一般管理指令（例如：清單、報表、暫停、刪除、重設等）。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數。

    Returns:
        bool: 如果處理了其中一個指令，則回傳 True；若皆未符合則回傳 False。
    """
    handled = True
    if args.list_jobs:
        _handle_list_jobs(manager, args)
    elif args.report:
        _handle_report(manager, args)
    elif args.export:
        _handle_export(manager, args)
    elif args.pause:
        logging.info("準備暫停任務 %s...", args.pause)
        if not manager.pause_job(args.pause):
            sys.exit(1)
        logging.info("已成功發送暫停指令，任務狀態已設為 paused。")
    elif args.delete:
        logging.info("準備刪除任務 %s...", args.delete)
        if not manager.delete_job(args.delete):
            sys.exit(1)
        logging.info("任務已成功刪除，相關佇列與外連記錄已清理。")
    elif args.reset:
        logging.info("準備重設任務 %s...", args.reset)
        if not manager.reset_job(args.reset):
            sys.exit(1)
        logging.info("任務已成功重設。")
    else:
        handled = False

    return handled


def _handle_resume_or_create(
    manager: JobManager, args: argparse.Namespace, global_config: dict[str, Any]
) -> None:
    """
    處理建立新任務或從中斷點恢復執行的指令。

    讀取指定的 YAML 設定檔進行驗證合併後，啟動或接管對應的爬蟲任務。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數。
        global_config (dict[str, Any]): 系統的全域設定字典。

    Raises:
        SystemExit: 當讀取設定失敗、驗證不通過或啟動爬蟲失敗時，終止程式並回傳錯誤碼 1。
    """
    config: dict[str, Any] = {}
    if args.config:
        config_path = args.config
        if not config_path.startswith(("job/", "./job/", "/")):
            config_path = os.path.join("job", config_path)
        try:
            config = load_config(config_path, allowed_directory="job")
        except FileNotFoundError:
            logging.error("找不到指定的設定檔: %s", config_path)
            sys.exit(1)
        except PermissionError as pe:
            logging.error("安全驗證失敗：%s", pe)
            sys.exit(1)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.error("讀取設定檔時發生錯誤: %s", e)
            sys.exit(1)

    crawler_config = merge_and_validate_crawler_config(config, global_config)

    if args.resume is not None:
        logging.info("正在恢復執行任務 %s...", args.resume)
        if args.config:
            logging.warning(
                "--resume 模式下 --config 參數將被忽略，任務將使用資料庫中的原始設定快照繼續執行。"
            )
        manager.run_job(job_id=args.resume, force=args.force)
        return

    try:
        start_url: str | None = config.get("start_url")
        target_domains: list[str] = config.get("target_domains", [])
        internal_domains: list[str] = config.get("internal_domains", [])

        if isinstance(target_domains, str):
            target_domains = [target_domains]
        if isinstance(internal_domains, str):
            internal_domains = [internal_domains]

        if not start_url:
            logging.error("設定檔中缺少必填參數: start_url")
            sys.exit(1)

        if not target_domains:
            logging.error("設定檔中缺少必填參數: target_domains (至少需包含一個網域)")
            sys.exit(1)

        logging.info("準備建立新任務...")
        job_id: str = manager.create_job(
            start_url,
            target_domains,
            internal_domains,
            crawler_config=crawler_config,
            user_id=args.user_id,
        )
        logging.info("成功建立任務 %s。爬蟲啟動中...", job_id)
        manager.run_job(job_id, crawler_config=crawler_config)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logging.error("啟動爬蟲時發生例外錯誤: %s", e)
        sys.exit(1)


def main() -> None:
    """
    CLI 的主要程式進入點。

    負責解析命令列參數、初始化環境與日誌、並根據參數指派對應的處理函式。

    Raises:
        SystemExit: 當全域設定讀取失敗、伺服器啟動錯誤等致命例外發生時。
    """
    args: argparse.Namespace | None = parse_args()
    if not args:
        return

    global_config_path = args.global_config
    if not global_config_path.startswith(("config/", "./config/", "/")):
        global_config_path = os.path.join("config", global_config_path)

    global_config: dict[str, Any] = {}
    try:
        global_config = load_config(global_config_path, allowed_directory="config")
    except FileNotFoundError:
        logging.warning("找不到全域設定檔: %s，將使用預設全域設定", global_config_path)
    except PermissionError as pe:
        logging.error("安全驗證失敗：%s", pe)
        sys.exit(1)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logging.error("讀取全域設定檔時發生錯誤: %s", e)
        sys.exit(1)

    setup_logging(global_config)
    db_url: str = global_config.get("db_url", "sqlite:///db/crawler.db")

    if args.create_admin:
        try:
            email = args.create_admin[0]
            create_admin(email)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.error("建立管理員帳號失敗: %s", e)
            sys.exit(1)
        return

    if args.serve:
        logging.info("啟動 Web 後端伺服器...")
        try:
            import uvicorn  # pylint: disable=import-outside-toplevel

            uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=args.reload)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.error("啟動 Web 伺服器失敗: %s", e)
            sys.exit(1)
        return

    manager: JobManager = JobManager(db_url=db_url)
    if _handle_job_management(manager, args):
        return

    _handle_resume_or_create(manager, args, global_config)


if __name__ == "__main__":
    main()
