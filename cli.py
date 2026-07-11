"""
網站連結檢查系統的命令列介面 (CLI)。

此腳本負責解析命令列參數、讀取 YAML 設定檔，
並透過 JobManager 啟動全新的任務或是恢復先前中斷的任務。
"""

import argparse
import json
import logging
import os
import re
import secrets
import string
import sys
from logging.handlers import RotatingFileHandler
from typing import cast

import yaml
from dotenv import load_dotenv

load_dotenv()

# pylint: disable=wrong-import-position
# isort: off
from backend.jobs.services.exporter import (  # noqa: E402
    export_full_report,
    export_external_job_results,
    export_internal_job_results,
    ExportOptions,
)
from backend.jobs.services.query_utils import ERROR_STATUS_FILTERS  # noqa: E402
from backend.jobs.services.notifier import subscribe_to_events  # noqa: E402

from crawler.config_utils import merge_and_validate_crawler_config  # noqa: E402
from crawler.manager import JobManager, JobCreateOptions, Job  # noqa: E402
# isort: on

# 設定初始的 logging，只輸出到畫面，確保 setup_logging 呼叫前的錯誤能被顯示
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def load_config(config_path: str, allowed_directory: str | None = None) -> dict[str, object]:
    """
    從指定的 YAML 檔案讀取設定值。

    Args:
        config_path (str): YAML 設定檔的檔案路徑。
        allowed_directory (str | None): 限制此設定檔只能放置於此目錄（或其子目錄）下。

    Returns:
        dict[str, object]: 讀取出來的設定字典 (Dictionary) 物件。

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
                raise PermissionError(f"設定檔 {config_path} 必須位於指定目錄 ({allowed_directory}) 下以符合資安規範")
        except ValueError as exc:
            raise PermissionError("無法比對設定檔路徑與允許目錄的安全路徑。") from exc

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging() -> None:
    """
    依據環境變數來套用 Logging 輸出層級與檔案路徑。
    """
    console_level_str = os.environ.get("LOG_CONSOLE_LEVEL", "INFO")
    file_level_str = os.environ.get("LOG_FILE_LEVEL", "DEBUG")
    log_file = os.environ.get("LOG_FILE_PATH", "log/crawler.log")

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

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # 設定 Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 設定 File Handler (加入 Log Rotation 機制，單一檔案最大 10MB，保留 5 份)
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
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
            print(
                "錯誤：系統中已存在管理員帳號。依據安全規範，後續管理員請透過後台網頁介面邀請，禁止使用 CLI 重複建立。"
            )
            sys.exit(1)

        random_password = generate_random_password()
        if existing:
            print(f"使用者 {email} 已存在，將更新其密碼並設為管理員。")
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
        print("請使用此密碼登入系統，登入後系統將會強制要求您設定新的安全密碼。")
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
        args.export_external,
        args.export_internal,
        args.export_full,
        args.pause,
        args.delete,
        args.reset,
        args.retry_failed,
        args.create_admin,
        args.serve,
        args.api_spawn is not None,
    ]
    return not any(commands)


def parse_args() -> argparse.Namespace | None:
    """
    設定並解析命令列參數。

    若未指定必要的參數 (例如：未帶任何任務相關操作參數)，則會印出命令列使用說明，並回傳 None。

    Returns:
        argparse.Namespace | None: 解析後的參數命名空間物件。若未提供必要參數則回傳 None。
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="網站連結檢查系統 (Link Checker)")

    # ---------------------------------------------------------
    # 群組 1：任務生命週期與調度 (Job Lifecycle & Scheduling)
    # ---------------------------------------------------------
    group_lifecycle = parser.add_argument_group("任務生命週期與調度 (Job Lifecycle & Scheduling)")
    group_lifecycle.add_argument("-c", "--config", type=str, help="YAML 設定檔的路徑 (建立新任務時必填)")
    group_lifecycle.add_argument("-u", "--user-id", type=str, help="(選填) 綁定任務的擁有者 ID")
    group_lifecycle.add_argument("-r", "--resume", type=str, help="欲恢復執行之任務 (Job) ID")
    group_lifecycle.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="(選填) 強制接管狀態卡在 running 的任務（搭配 --resume 使用）",
    )
    group_lifecycle.add_argument(
        "-p",
        "--pause",
        type=str,
        metavar="JOB_ID",
        help="暫停指定任務 (僅在任務狀態為 running 時生效)",
    )
    group_lifecycle.add_argument(
        "-d",
        "--delete",
        type=str,
        metavar="JOB_ID",
        help="刪除指定任務，並清理其所有佇列與外連記錄",
    )
    group_lifecycle.add_argument(
        "-R",
        "--reset",
        type=str,
        metavar="JOB_ID",
        help="重設指定任務，清除已探索外連並將狀態與佇列歸零",
    )
    group_lifecycle.add_argument(
        "-T",
        "--retry-failed",
        type=str,
        metavar="JOB_ID",
        help="局部重試指定任務中爬取失敗的內部網頁與包含無效外連的網頁",
    )

    # ---------------------------------------------------------
    # 群組 2：報表檢視與結果匯出 (Reporting & Exporting)
    # ---------------------------------------------------------
    group_report = parser.add_argument_group("報表檢視與結果匯出 (Reporting & Exporting)")
    group_report.add_argument("--list-jobs", action="store_true", help="列出所有已建立的爬蟲任務")
    group_report.add_argument("--report", type=str, help="檢視指定任務的詳細進度與統計報表")
    group_report.add_argument(
        "--export-external",
        type=str,
        metavar="JOB_ID",
        help="指定任務 ID，將該任務尋獲的外部連結匯出 (預設為 CSV，若帶有 --json 則為 JSON)",
    )
    group_report.add_argument(
        "--export-internal",
        metavar="JOB_ID",
        help="指定任務 ID，將該任務的內部網頁爬取紀錄匯出 (預設為 CSV，若帶有 --json 則為 JSON)",
    )
    group_report.add_argument(
        "--export-full",
        type=str,
        metavar="JOB_ID",
        help="將指定任務 ID 的完整報表 (ZIP 壓縮檔) 匯出",
    )
    group_report.add_argument(
        "--output",
        type=str,
        metavar="FILE_PATH",
        help="(選填) 指定匯出檔案的路徑與名稱，預設為 report/<JOB_ID>.csv (或 .json)",
    )
    group_report.add_argument(
        "--filter",
        type=str,
        choices=[
            "dead",
            "broken",
            "insecure",
            *ERROR_STATUS_FILTERS,
            "healthy",
            "all",
        ],
        help="(選填) 搭配 --export-external 使用，篩選匯出內容",
    )
    group_report.add_argument(
        "--exclude",
        type=str,
        help="(選填) 搭配 --export-external 使用，排除指定的目標網域（多個以逗號分隔，例如: facebook.com,youtube.com）",
    )
    group_report.add_argument(
        "--group-by",
        type=str,
        choices=["none", "target", "source", "domain"],
        default="none",
        help="(選填) 搭配 --export-external，指定聚合模式 (target:依外連, source:依來源頁面, domain:依網域)",
    )
    group_report.add_argument(
        "--json",
        action="store_true",
        help="(選填) 以 JSON 格式輸出或導出結果 (支援 --list-jobs, --report, --export-external, --export-internal)",
    )

    # ---------------------------------------------------------
    # 群組 3：全域設定與系統維運 (Global & System Admin)
    # ---------------------------------------------------------
    group_system = parser.add_argument_group("全域設定與系統維運 (Global & System Admin)")
    group_system.add_argument(
        "-g",
        "--global-config",
        type=str,
        default=os.environ.get("GLOBAL_CONFIG_PATH", "config/config_global.yaml"),
        help="全域 YAML 設定檔的路徑",
    )
    group_system.add_argument(
        "--serve",
        action="store_true",
        help="啟動 Web 後端伺服器 (FastAPI / Uvicorn)",
    )
    group_system.add_argument(
        "--reload",
        action="store_true",
        help="(選填) 搭配 --serve 使用，啟用 Uvicorn 的開發模式熱重載",
    )
    group_system.add_argument(
        "--create-admin",
        nargs=1,
        metavar="EMAIL",
        help="建立或更新系統管理員帳號 (隨機產生密碼並設為待設密狀態)",
    )
    group_system.add_argument(
        "--api-spawn",
        type=str,
        metavar="JOB_ID",
        help=argparse.SUPPRESS,  # API 背景呼叫專用
    )

    args: argparse.Namespace = parser.parse_args()

    if _is_help_needed(args):
        parser.print_help()
        return None

    return args


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
        print(f"{'Job ID':<38} | {'User ID':<20} | {'Status':<10} | {'Created At':<20} | {'Start URL'}")
        print("-" * 120)
        for j in jobs:
            uid = j.get("user_id") or "N/A"
            print(f"{j['id']:<38} | {uid:<20} | {j['status']:<10} | {j['created_at']:<20} | {j['start_url']}")
        print("====================\n")


def _handle_report(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理檢視報表的指令。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含報表 ID 與 json 選項。

    Raises:
        SystemExit: 當找不到任務時拋出並結束程式。
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
        queue_stats = cast(dict[str, object], report["queue"])
        print(f"  總計網址數: {queue_stats['total']}")
        print(f"  已完成 (Completed): {queue_stats['completed']}")
        print(f"  已略過 (Skipped):   {queue_stats['skipped']}")
        print(f"  等待中 (Pending):   {queue_stats['pending']}")
        print(f"  已失敗 (Failed):    {queue_stats['failed']}")
        print("-" * 20)
        print("【產出成果】")
        print(f"  尋獲外部連結數: {report['external_links']}")
        print("====================\n")


def _handle_export_external(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理匯出結果的指令。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含匯出目標、篩選與群組等選項。

    Raises:
        SystemExit: 當匯出失敗時拋出並結束程式。
    """
    ext = ".json" if args.json else ".csv"
    output_path = args.output if args.output else f"report/{args.export_external}{ext}"
    logging.info("準備將任務 %s 外部連結匯出至 %s...", args.export_external, output_path)

    with manager.session_factory() as db:
        job = db.query(Job).filter(Job.id == args.export_external).first()
        if not job:
            logging.error("找不到任務 %s", args.export_external)
            sys.exit(1)

        options = ExportOptions(
            status_filter=args.filter,
            group_by=args.group_by or "none",
            exclude=args.exclude,
        )
        success = export_external_job_results(
            session_factory=manager.session_factory,
            job_id=args.export_external,
            output_path=output_path,
            options=options,
        )
        if success:
            logging.info("匯出成功！")
        else:
            sys.exit(1)


def _handle_export_internal(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理匯出內部爬取結果的邏輯。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含匯出目標等選項。

    Raises:
        SystemExit: 當匯出失敗時拋出並結束程式。
    """
    ext = ".json" if args.json else ".csv"
    output_path = args.output if args.output else f"report/{args.export_internal}_internal{ext}"
    logging.info("準備將任務 %s 內部爬取紀錄匯出至 %s...", args.export_internal, output_path)

    with manager.session_factory() as db:
        job = db.query(Job).filter(Job.id == args.export_internal).first()
        if not job:
            logging.error("找不到任務 %s", args.export_internal)
            return

        success = export_internal_job_results(
            session_factory=manager.session_factory,
            job_id=args.export_internal,
            output_path=output_path,
        )
        if success:
            logging.info("匯出成功！檔案已儲存於: %s", output_path)


def _handle_export_full(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理匯出完整報表 (ZIP) 的指令。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含匯出目標等選項。

    Raises:
        SystemExit: 當匯出失敗時拋出並結束程式。
    """
    output_path = args.output if args.output else f"report/{args.export_full}_full_report.zip"
    if not output_path.endswith(".zip"):
        output_path += ".zip"
    logging.info("準備將任務 %s 的完整報表匯出至 %s...", args.export_full, output_path)
    success = export_full_report(
        session_factory=manager.session_factory,
        job_id=args.export_full,
        output_path=output_path,
    )
    if success:
        logging.info("匯出成功！")
    else:
        sys.exit(1)


def _handle_pause(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理暫停任務的指令。

    向指定的任務發出暫停訊號，並將任務狀態設為 paused。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含欲暫停的任務 ID (args.pause)。

    Raises:
        SystemExit: 當暫停操作失敗時拋出並結束程式。
    """
    logging.info("準備暫停任務 %s...", args.pause)
    if not manager.pause_job(args.pause):
        sys.exit(1)
    logging.info("已成功發送暫停指令，任務狀態已設為 paused。")


def _handle_delete(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理刪除任務的指令。

    刪除指定任務，並清理關聯的所有佇列資料與外連紀錄。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含欲刪除的任務 ID (args.delete)。

    Raises:
        SystemExit: 當刪除操作失敗時拋出並結束程式。
    """
    logging.info("準備刪除任務 %s...", args.delete)
    if not manager.delete_job(args.delete):
        sys.exit(1)
    logging.info("任務已成功刪除，相關佇列與外連記錄已清理。")


def _handle_reset(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理重設任務的指令。

    將指定任務的狀態重置，並清空已發現的連結與執行紀錄，使其可重新開始。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含欲重設的任務 ID (args.reset)。

    Raises:
        SystemExit: 當重設操作失敗時拋出並結束程式。
    """
    logging.info("準備重設任務 %s...", args.reset)
    if not manager.reset_job(args.reset):
        sys.exit(1)
    logging.info("任務已成功重設。")


def _handle_retry_failed(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理局部重試任務的指令。

    將指定任務中內部抓取失敗的網頁狀態重設為等待中，以便後續可透過 resume 指令重新爬取。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含欲重試的任務 ID (args.retry_failed)。

    Raises:
        SystemExit: 當重試操作失敗時拋出並結束程式。
    """
    logging.info("準備局部重試任務 %s 的失敗項目...", args.retry_failed)
    if not manager.retry_failed_job(args.retry_failed):
        sys.exit(1)
    logging.info("任務的失敗項目已成功重置為 pending。您可以透過 --resume 再次啟動該任務。")


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
    elif args.export_external:
        _handle_export_external(manager, args)
    elif args.export_internal:
        _handle_export_internal(manager, args)
    elif args.export_full:
        _handle_export_full(manager, args)
    elif args.pause:
        _handle_pause(manager, args)
    elif args.delete:
        _handle_delete(manager, args)
    elif args.reset:
        _handle_reset(manager, args)
    elif args.retry_failed:
        _handle_retry_failed(manager, args)
    else:
        handled = False

    return handled


def _handle_resume(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理恢復執行指定任務的指令。

    從資料庫中讀取原始設定快照並繼續尚未完成的爬蟲任務。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含欲恢復的任務 ID (args.resume) 與是否強制執行的選項 (args.force)。
    """
    logging.info("正在恢復執行任務 %s...", args.resume)
    if args.config:
        logging.warning("--resume 模式下 --config 參數將被忽略，任務將使用資料庫中的原始設定快照繼續執行。")
    logging.info("開始接續執行任務...")
    manager.run_job(job_id=args.resume, force=args.force)


def _handle_api_spawn(manager: JobManager, args: argparse.Namespace) -> None:
    """
    處理 API 在背景產生的任務啟動指令。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含 API 啟動的任務 ID (args.api_spawn) 與強制選項。
    """
    logging.info("API 觸發任務啟動程序: %s", args.api_spawn)
    logging.info("接收到背景執行訊號，強制啟動任務...")
    manager.run_job(job_id=args.api_spawn, force=args.force, is_api_spawn=True)


def _load_job_config(config_path: str) -> dict[str, object]:
    """
    讀取並解析任務專用的 YAML 設定檔。

    若未提供絕對路徑，則預設從 `job/` 目錄中尋找。

    Args:
        config_path (str): 任務設定檔的路徑。

    Returns:
        dict[str, object]: 解析後的任務設定字典。

    Raises:
        SystemExit: 當設定檔不存在、權限不足或格式錯誤時終止程式。
    """
    if not config_path.startswith(("job/", "./job/", "/")):
        config_path = os.path.join("job", config_path)
    try:
        return load_config(config_path, allowed_directory="job")
    except FileNotFoundError:
        logging.error("找不到指定的設定檔: %s", config_path)
        sys.exit(1)
    except PermissionError as pe:
        logging.error("安全驗證失敗：%s", pe)
        sys.exit(1)
    except yaml.YAMLError as e:
        logging.error("讀取設定檔時發生格式錯誤: %s", e)
        sys.exit(1)


def _normalize_domains(raw_domains: object) -> list[str]:
    """
    將傳入的網域設定統一正規化為字串列表。

    支援處理單一字串、列表或其他可轉換型別，並會自動去除空白與無效項目。

    Args:
        raw_domains (object): 從設定檔讀取出來的原始網域資料。

    Returns:
        list[str]: 正規化後的網域字串列表。
    """
    if isinstance(raw_domains, str):
        raw_domains = [raw_domains]
    elif not isinstance(raw_domains, list):
        raw_domains = [str(raw_domains)] if raw_domains is not None else []
    return [str(d).strip() for d in raw_domains if str(d).strip()]


def _create_and_run_new_job(
    manager: JobManager,
    args: argparse.Namespace,
    config: dict[str, object],
    crawler_config: dict[str, object],
) -> None:
    """
    驗證設定參數，建立全新任務並啟動爬蟲。

    解析任務所需的起始網址與目標網域，若驗證通過則交由 manager 建立任務，並隨即啟動執行。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數，包含可選的綁定使用者 ID。
        config (dict[str, object]): 讀取自 YAML 的原始任務設定。
        crawler_config (dict[str, object]): 已合併全域設定的爬蟲執行參數。

    Raises:
        SystemExit: 當缺少必填參數、網址格式錯誤或啟動爬蟲發生例外時終止程式。
    """
    try:
        start_url: str | None = str(config.get("start_url")).strip() if config.get("start_url") is not None else None
        target_domains = _normalize_domains(config.get("target_domains", []))
        trusted_domains = _normalize_domains(config.get("trusted_domains", []))

        if not start_url:
            logging.error("設定檔中缺少必填參數: start_url")
            sys.exit(1)

        if not (start_url.startswith("http://") or start_url.startswith("https://")):
            logging.error("設定檔參數錯誤: start_url 必須以 http:// 或 https:// 開頭")
            sys.exit(1)

        if not target_domains:
            logging.error("設定檔中缺少必填參數: target_domains (至少需包含一個網域)")
            sys.exit(1)

        logging.info("準備建立新任務...")
        job_id: str = manager.create_job(
            JobCreateOptions(
                start_url=start_url,
                target_domains=target_domains,
                trusted_domains=trusted_domains,
                crawler_config=crawler_config,
                user_id=args.user_id,
            )
        )
        logging.info("成功建立任務 %s。爬蟲啟動中...", job_id)
        # --- Phase 4: Execution ---
        manager.run_job(job_id, crawler_config=crawler_config)
    except (ValueError, RuntimeError, OSError, TypeError) as e:
        logging.error("啟動爬蟲時發生例外錯誤: %s", e)
        sys.exit(1)


def _handle_resume_or_create(manager: JobManager, args: argparse.Namespace, global_config: dict[str, object]) -> None:
    """
    處理建立新任務或從中斷點恢復執行的指令。

    讀取指定的 YAML 設定檔進行驗證合併後，啟動或接管對應的爬蟲任務。

    Args:
        manager (JobManager): JobManager 實例。
        args (argparse.Namespace): 命令列參數。
        global_config (dict[str, object]): 系統的全域設定字典。

    Raises:
        SystemExit: 當讀取設定失敗、驗證不通過或啟動爬蟲失敗時，終止程式並回傳錯誤碼 1。
    """
    if args.resume is not None:
        _handle_resume(manager, args)
        return

    config: dict[str, object] = {}
    if args.config:
        config = _load_job_config(args.config)

    crawler_config = merge_and_validate_crawler_config(config, global_config)
    _create_and_run_new_job(manager, args, config, crawler_config)


def _load_global_config(args: argparse.Namespace) -> dict[str, object]:
    """
    讀取並解析系統全域 YAML 設定檔。

    若未提供絕對路徑，則預設從 `config/` 目錄中尋找。若檔案不存在則預設回傳空字典。

    Args:
        args (argparse.Namespace): 命令列參數，包含全域設定檔路徑。

    Returns:
        dict[str, object]: 解析後的全域設定字典。

    Raises:
        SystemExit: 當全域設定檔權限不足或格式解析錯誤時終止程式。
    """
    global_config_path = args.global_config
    if not global_config_path.startswith(("config/", "./config/", "/")):
        global_config_path = os.path.join("config", global_config_path)

    try:
        return load_config(global_config_path, allowed_directory="config")
    except FileNotFoundError:
        logging.warning("找不到全域設定檔: %s，將使用預設全域設定", global_config_path)
        return {}
    except PermissionError as pe:
        logging.error("安全驗證失敗：%s", pe)
        sys.exit(1)
    except yaml.YAMLError as e:
        logging.error("讀取全域設定檔時發生格式錯誤: %s", e)
        sys.exit(1)


def _handle_create_admin(args: argparse.Namespace) -> None:
    """
    處理建立管理員帳號的指令。

    提取命令列提供的信箱地址，並觸發管理員帳號建立與密碼產生邏輯。

    Args:
        args (argparse.Namespace): 命令列參數，包含目標信箱。

    Raises:
        SystemExit: 當信箱格式錯誤或資料庫執行發生異常時終止程式。
    """
    try:
        email = args.create_admin[0]
        create_admin(email)
    except (ValueError, RuntimeError, TypeError) as e:
        logging.error("建立管理員帳號失敗: %s", e)
        sys.exit(1)


def _handle_serve(args: argparse.Namespace) -> None:
    """
    處理啟動 Web 後端伺服器的指令。

    透過 Uvicorn 啟動 FastAPI 應用程式，並依據參數決定是否開啟熱重載。

    Args:
        args (argparse.Namespace): 命令列參數，包含是否啟用熱重載 (args.reload)。

    Raises:
        SystemExit: 當缺少必要套件或啟動伺服器發生例外錯誤時終止程式。
    """
    logging.info("啟動 Web 後端伺服器...")
    print("\n" + "=" * 50)
    print("🚀 系統已準備就緒！")
    print("👉 請打開瀏覽器，前往： http://127.0.0.1:8000")
    print("=" * 50 + "\n")
    try:
        import uvicorn  # pylint: disable=import-outside-toplevel

        uvicorn.run(
            "backend.main:app",
            host="0.0.0.0",
            port=8000,
            reload=args.reload,
            proxy_headers=True,
            forwarded_allow_ips="*",
        )
    except (ImportError, RuntimeError, OSError) as e:
        logging.error("啟動 Web 伺服器失敗: %s", e)
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

    global_config = _load_global_config(args)
    setup_logging()
    db_url: str = os.environ.get("CRAWLER_DB_URL", "sqlite:///db/crawler.db")

    if args.create_admin:
        _handle_create_admin(args)
        return

    if args.serve:
        _handle_serve(args)
        return

    manager: JobManager = JobManager(db_url=db_url)
    try:
        subscribe_to_events(manager.session_factory)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logging.error("註冊事件監聽失敗: %s", e)

    if args.api_spawn:
        _handle_api_spawn(manager, args)
        return

    if _handle_job_management(manager, args):
        return

    _handle_resume_or_create(manager, args, global_config)


if __name__ == "__main__":
    main()
