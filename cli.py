"""
外部連結檢查爬蟲的命令列介面 (CLI)。

此腳本負責解析命令列參數、讀取 YAML 設定檔，
並透過 JobManager 啟動全新的任務或是恢復先前中斷的任務。
"""
import argparse
import yaml
import logging
import os
from typing import Any
from crawler.manager import JobManager

# 設定初始的 logging，只輸出到畫面，確保 setup_logging 呼叫前的錯誤能被顯示
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def load_config(config_path: str, allowed_directory: str | None = None) -> dict[str, Any]:
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
                raise PermissionError(f"設定檔 {config_path} 必須位於指定目錄 ({allowed_directory}) 下以符合資安規範")
        except ValueError:
            raise PermissionError(f"無法比對設定檔路徑與允許目錄的安全路徑。")

    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def setup_logging(global_config: dict[str, Any]) -> None:
    """
    依據全域設定檔來套用 Logging 輸出層級與檔案路徑。

    會從全域設定中讀取 `logging` 區塊，分別設定畫面 (Console) 與檔案 (File) 
    的輸出層級與日誌檔案路徑。

    Args:
        global_config (dict[str, Any]): 全域設定字典物件，需包含系統的全域設定參數。
    """
    logging_config = global_config.get('logging', {})
    
    console_level_str = logging_config.get('console_level', 'INFO')
    file_level_str = logging_config.get('file_level', 'DEBUG')
    log_file = logging_config.get('log_file', 'log/crawler.log')

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

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 設定 Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 設定 File Handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

def parse_args() -> argparse.Namespace | None:
    """
    設定並解析命令列參數。

    若未指定必要的參數 (例如：未帶任何任務相關操作參數)，則會印出命令列使用說明，並回傳 None。

    Returns:
        argparse.Namespace | None: 解析後的參數命名空間物件。若未提供必要參數則回傳 None。
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="外部連結檢查爬蟲 (External Link Checker Crawler)")
    parser.add_argument('-g', '--global-config', type=str, default='config/config_global.yaml', help='全域 YAML 設定檔的路徑')
    parser.add_argument('-c', '--config', type=str, help='YAML 設定檔的路徑')
    parser.add_argument('-u', '--user-id', type=str, help='(選填) 綁定任務的擁有者 ID')
    parser.add_argument('-r', '--resume', type=str, help='欲恢復執行之任務 (Job) ID')
    parser.add_argument('-f', '--force', action='store_true', help='(選填) 強制接管狀態卡在 running 的任務（搭配 --resume 使用）')
    parser.add_argument('--list-jobs', action='store_true', help='列出所有已建立的爬蟲任務')
    parser.add_argument('--pause', type=str, metavar='JOB_ID', help='暫停指定任務 (僅在任務狀態為 running 時生效)')
    parser.add_argument('--delete', type=str, metavar='JOB_ID', help='刪除指定任務，並清理其所有佇列與外連記錄')
    parser.add_argument('--reset', type=str, metavar='JOB_ID', help='重設指定任務，清除已探索外連並將狀態與佇列歸零')
    parser.add_argument('--report', type=str, help='檢視指定任務的詳細進度與統計報表')
    parser.add_argument('--export', type=str, metavar='JOB_ID', help='將指定任務 ID 所找到的外部連結匯出')
    parser.add_argument('--output', type=str, metavar='FILE_PATH', help='(選填) 指定匯出檔案的路徑與名稱，預設為 report/<JOB_ID>.csv (或 .json)')
    parser.add_argument('--filter', type=str, choices=['dead', 'broken', 'unapproved'], help='(選填) 搭配 --export 使用，篩選匯出內容 (dead: DNS解析失敗, broken: HTTP錯誤或連線失敗, unapproved: 不在白名單內的外連)')
    parser.add_argument('--group', action='store_true', help='(選填) 搭配 --export 使用，按外部目標連結進行去重與聚合導出')
    parser.add_argument('--json', action='store_true', help='(選填) 以 JSON 格式輸出或導出結果 (支援 --list-jobs, --report, --export)')
    
    args: argparse.Namespace = parser.parse_args()

    if not args.config and args.resume is None and not args.list_jobs and not args.report and not args.export and not args.pause and not args.delete and not args.reset:
        parser.print_help()
        return None
        
    return args

def merge_and_validate_crawler_config(config: dict[str, Any], global_config: dict[str, Any]) -> dict[str, Any]:
    """
    合併全域與個別的爬蟲設定，並確保個別設定遵守全域上下限。

    此函式會過濾掉個別設定中不允許覆寫的項目，將缺少的項目以全域設定的預設值補齊，
    聯集合併需忽略的副檔名清單，最後確保 `timeout`、`delay` 與 `retries` 
    等參數皆落在全域設定規範的上下限範圍內。

    Args:
        config (dict[str, Any]): 個別爬蟲任務的設定字典物件。
        global_config (dict[str, Any]): 全域設定字典物件。

    Returns:
        dict[str, Any]: 合併且經過驗證後的爬蟲專屬設定字典物件。
    """
    crawler_config: dict[str, Any] = config.get('crawler', {})
    
    # 限制個別設定只能設定允許的項目
    allowed_crawler_keys: set[str] = {
        'timeout', 'delay', 'ignore_extensions', 'retries', 'mime_type_filter', 
        'ignore_regexes', 'user_agent', 'approved_domains', 'ssl_exempt_domains', 
        'domain_delays', 'max_depth', 'max_pages', 'proxy_url', 'webhook_url'
    }
    for key in list(crawler_config.keys()):
        if key not in allowed_crawler_keys:
            logging.warning(f"個別設定 config.yaml 不允許覆寫或設定 crawler.{key}，此設定將被忽略。")
            del crawler_config[key]

    global_crawler_config: dict[str, Any] = global_config.get('crawler', {})
    
    # 套用全域預設值
    if 'timeout' not in crawler_config:
        crawler_config['timeout'] = global_crawler_config.get('timeout', 30)
        
    if 'delay' not in crawler_config:
        crawler_config['delay'] = global_crawler_config.get('delay', 3.0)

    if 'retries' not in crawler_config:
        crawler_config['retries'] = global_crawler_config.get('retries', 3)

    if 'mime_type_filter' not in crawler_config:
        crawler_config['mime_type_filter'] = global_crawler_config.get('mime_type_filter', {
            'enabled': True,
            'allowed_types': ['text/html', 'application/xhtml+xml']
        })

    # 聯集合併全域與個別的 ignore_extensions
    global_ignore_extensions: list[str] = global_crawler_config.get('ignore_extensions', [])
    local_ignore_extensions: list[str] = crawler_config.get('ignore_extensions', [])
    if global_ignore_extensions or local_ignore_extensions:
        crawler_config['ignore_extensions'] = list(set(global_ignore_extensions + local_ignore_extensions))

    # 聯集合併全域與個別的 ignore_regexes
    global_ignore_regexes: list[str] = global_crawler_config.get('ignore_regexes', [])
    local_ignore_regexes: list[str] = crawler_config.get('ignore_regexes', [])
    if global_ignore_regexes or local_ignore_regexes:
        crawler_config['ignore_regexes'] = list(set(global_ignore_regexes + local_ignore_regexes))

    # 套用全域預設值或預設瀏覽器 User-Agent
    if 'user_agent' not in crawler_config:
        crawler_config['user_agent'] = global_crawler_config.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # 聯集合併全域與個別的 approved_domains
    global_approved_domains: list[str] = global_crawler_config.get('approved_domains', [])
    local_approved_domains: list[str] = crawler_config.get('approved_domains', [])
    if global_approved_domains or local_approved_domains:
        crawler_config['approved_domains'] = list(set(global_approved_domains + local_approved_domains))
    else:
        crawler_config['approved_domains'] = []

    # 聯集合併全域與個別的 ssl_exempt_domains
    global_ssl_exempt: list[str] = global_crawler_config.get('ssl_exempt_domains', [])
    local_ssl_exempt: list[str] = crawler_config.get('ssl_exempt_domains', [])
    if global_ssl_exempt or local_ssl_exempt:
        crawler_config['ssl_exempt_domains'] = list(set(global_ssl_exempt + local_ssl_exempt))
    else:
        crawler_config['ssl_exempt_domains'] = []

    # 合併全域與個別的 domain_delays
    global_domain_delays: dict = global_crawler_config.get('domain_delays', {})
    local_domain_delays: dict = crawler_config.get('domain_delays', {})
    crawler_config['domain_delays'] = {**global_domain_delays, **local_domain_delays}

    # 合併資源與機密配置
    if 'max_depth' not in crawler_config:
        crawler_config['max_depth'] = global_crawler_config.get('max_depth', None)
    if 'max_pages' not in crawler_config:
        crawler_config['max_pages'] = global_crawler_config.get('max_pages', None)
    if 'proxy_url' not in crawler_config:
        crawler_config['proxy_url'] = global_crawler_config.get('proxy_url', None)
    if 'webhook_url' not in crawler_config:
        crawler_config['webhook_url'] = global_crawler_config.get('webhook_url', None)

    # 優先從環境變數載入關鍵配置，防範機密憑證洩漏
    import os
    env_proxy = os.environ.get("CRAWLER_PROXY_URL")
    if env_proxy:
        crawler_config['proxy_url'] = env_proxy
        
    env_webhook = os.environ.get("CRAWLER_WEBHOOK_URL")
    if env_webhook:
        crawler_config['webhook_url'] = env_webhook
        
    env_ssl_exempt = os.environ.get("CRAWLER_SSL_EXEMPT_DOMAINS")
    if env_ssl_exempt:
        crawler_config['ssl_exempt_domains'] = list(set(
            crawler_config.get('ssl_exempt_domains', []) + 
            [d.strip() for d in env_ssl_exempt.split(',') if d.strip()]
        ))

    # 強制套用全域上下限
    min_timeout: int = global_crawler_config.get('min_timeout', 30)
    max_timeout: int = global_crawler_config.get('max_timeout', 120)
    min_delay: float = global_crawler_config.get('min_delay', 3.0)
    max_delay: float = global_crawler_config.get('max_delay', 6.0)
    min_retries: int = global_crawler_config.get('min_retries', 0)
    max_retries: int = global_crawler_config.get('max_retries', 5)

    if crawler_config['timeout'] < min_timeout:
        logging.warning(f"個別設定的 timeout ({crawler_config['timeout']}) 小於全域最小值 ({min_timeout})，將強制套用全域最小值。")
        crawler_config['timeout'] = min_timeout
    elif crawler_config['timeout'] > max_timeout:
        logging.warning(f"個別設定的 timeout ({crawler_config['timeout']}) 大於全域最大值 ({max_timeout})，將強制套用全域最大值。")
        crawler_config['timeout'] = max_timeout

    if crawler_config['delay'] < min_delay:
        logging.warning(f"個別設定的 delay ({crawler_config['delay']}) 小於全域最小值 ({min_delay})，將強制套用全域最小值。")
        crawler_config['delay'] = min_delay
    elif crawler_config['delay'] > max_delay:
        logging.warning(f"個別設定的 delay ({crawler_config['delay']}) 大於全域最大值 ({max_delay})，將強制套用全域最大值。")
        crawler_config['delay'] = max_delay

    if crawler_config['retries'] < min_retries:
        logging.warning(f"個別設定的 retries ({crawler_config['retries']}) 小於全域最小值 ({min_retries})，將強制套用全域最小值。")
        crawler_config['retries'] = min_retries
    elif crawler_config['retries'] > max_retries:
        logging.warning(f"個別設定的 retries ({crawler_config['retries']}) 大於全域最大值 ({max_retries})，將強制套用全域最大值。")
        crawler_config['retries'] = max_retries

    return crawler_config

def main() -> None:
    """
    CLI 的主要程式進入點。

    負責協調參數解析、設定讀取、初始化日誌模組，並根據使用者傳入的指令執行對應的操作
    (如：列出任務、顯示報表、匯出結果、恢復中斷的任務或建立並執行全新任務)。

    Returns:
        None
    """
    args: argparse.Namespace | None = parse_args()
    if not args:
        return

    global_config: dict[str, Any] = {}
    try:
        global_config = load_config(args.global_config, allowed_directory='config')
    except FileNotFoundError:
        logging.warning(f"找不到全域設定檔: {args.global_config}，將使用預設全域設定")
    except PermissionError as pe:
        logging.error(f"安全驗證失敗：{pe}")
        return
    except Exception as e:
        logging.error(f"讀取全域設定檔時發生錯誤: {e}")
        return

    setup_logging(global_config)

    db_url: str = global_config.get('db_url', 'sqlite:///db/crawler.db')
    manager: JobManager = JobManager(db_url=db_url)

    if args.list_jobs:
        jobs = manager.get_all_jobs(user_id=args.user_id)
        if args.json:
            import json
            print(json.dumps(jobs, ensure_ascii=False, indent=2))
        else:
            print("\n=== 爬蟲任務列表 ===")
            print(f"{'Job ID':<38} | {'User ID':<20} | {'Status':<10} | {'Created At':<20} | {'Start URL'}")
            print("-" * 120)
            for j in jobs:
                uid = j.get('user_id') or 'N/A'
                print(f"{j['id']:<38} | {uid:<20} | {j['status']:<10} | {j['created_at']:<20} | {j['start_url']}")
            print("====================\n")
        return

    if args.report:
        report = manager.get_job_report(args.report)
        if not report:
            logging.error(f"找不到指定的任務 ID: {args.report}")
            return
        
        if args.json:
            import json
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"\n=== 任務進度報表 ===")
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
        return

    if args.export:
        ext = '.json' if args.json else '.csv'
        output_path = args.output if args.output else f"report/{args.export}{ext}"
        logging.info(f"準備將任務 {args.export} 匯出至 {output_path}...")
        success = manager.export_job_results(args.export, output_path, status_filter=args.filter, export_group=args.group)
        if success:
            logging.info("匯出成功！")
        return

    if args.pause:
        logging.info(f"準備暫停任務 {args.pause}...")
        if manager.pause_job(args.pause):
            logging.info("已成功發送暫停指令，任務狀態已設為 paused。")
        return

    if args.delete:
        logging.info(f"準備刪除任務 {args.delete}...")
        if manager.delete_job(args.delete):
            logging.info("任務已成功刪除，相關佇列與外連記錄已清理。")
        return

    if args.reset:
        logging.info(f"準備重設任務 {args.reset}...")
        if manager.reset_job(args.reset):
            logging.info("任務已成功重設。")
        return

    config: dict[str, Any] = {}
    if args.config:
        config_path = args.config
        # 若路徑為單純的檔名，未以 job/ 開頭且無絕對/相對路徑導向，自動補上 job/ 
        if not config_path.startswith(('job/', './job/', '/')):
            config_path = os.path.join('job', config_path)
        try:
            config = load_config(config_path, allowed_directory='job')
        except FileNotFoundError:
            logging.error(f"找不到指定的設定檔: {config_path}")
            return
        except PermissionError as pe:
            logging.error(f"安全驗證失敗：{pe}")
            return
        except Exception as e:
            logging.error(f"讀取設定檔時發生錯誤: {e}")
            return

    crawler_config: dict[str, Any] = merge_and_validate_crawler_config(config, global_config)

    # 如果帶有 --resume 參數，則進行任務恢復
    if args.resume is not None:
        logging.info(f"正在恢復執行任務 {args.resume}...")
        # 恢復任務時不傳入 crawler_config，讓 manager 去讀資料庫
        manager.run_job(job_id=args.resume, force=args.force)
        return

    try:
        start_url: str | None = config.get('start_url')
        target_domains: list[str] = config.get('target_domains', [])
        internal_domains: list[str] = config.get('internal_domains', [])
        
        if not start_url:
            logging.error("設定檔中缺少必填參數: start_url")
            return
            
        logging.info("準備建立新任務...")
        job_id: str = manager.create_job(start_url, target_domains, internal_domains, crawler_config=crawler_config, user_id=args.user_id)
        logging.info(f"成功建立任務 {job_id}。爬蟲啟動中...")
        
        manager.run_job(job_id, crawler_config=crawler_config)
        
    except Exception as e:
        logging.error(f"啟動爬蟲時發生例外錯誤: {e}")

if __name__ == '__main__':
    main()
