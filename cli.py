"""
外部連結檢查爬蟲的命令列介面 (CLI)。

此腳本負責解析命令列參數、讀取 YAML 設定檔，
並透過 JobManager 啟動全新的任務或是恢復先前中斷的任務。
"""

import argparse
import yaml
import logging
from typing import Any
from crawler.manager import JobManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def load_config(config_path: str) -> dict[str, Any]:
    """
    從指定的 YAML 檔案讀取設定值。

    Args:
        config_path (str): YAML 設定檔的檔案路徑。

    Returns:
        dict[str, Any]: 讀取出來的設定字典 (Dictionary) 物件。
    """
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def parse_args() -> argparse.Namespace | None:
    """
    設定並解析命令列參數。
    若未指定必要的參數，則印出使用說明並回傳 None。
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="外部連結檢查爬蟲 (External Link Checker Crawler)")
    parser.add_argument('-c', '--config', type=str, help='YAML 設定檔的路徑')
    parser.add_argument('-g', '--global-config', type=str, default='config_global.yaml', help='全域 YAML 設定檔的路徑')
    parser.add_argument('-r', '--resume', type=str, help='欲恢復執行之任務 (Job) ID')
    parser.add_argument('-l', '--list-jobs', action='store_true', help='列出所有已建立的爬蟲任務')
    parser.add_argument('--report', type=str, help='檢視指定任務的詳細進度與統計報表')
    parser.add_argument('--export', type=str, help='將指定任務找到的外部連結匯出為 CSV')
    parser.add_argument('-o', '--output', type=str, help='CSV 匯出路徑 (搭配 --export 使用)')
    args: argparse.Namespace = parser.parse_args()

    if not args.config and args.resume is None and not args.list_jobs and not args.report and not args.export:
        parser.print_help()
        return None
        
    return args

def setup_logging(global_config: dict[str, Any]) -> None:
    """
    依據全域設定檔來套用 Logging 輸出層級。
    """
    log_level_str: str = global_config.get('logging_level', 'INFO').upper()
    log_level: int = getattr(logging, log_level_str, logging.INFO)
    logging.getLogger().setLevel(log_level)

def merge_and_validate_crawler_config(config: dict[str, Any], global_config: dict[str, Any]) -> dict[str, Any]:
    """
    合併全域與個別的爬蟲設定，並確保個別設定遵守全域上下限。
    """
    crawler_config: dict[str, Any] = config.get('crawler', {})
    
    # 限制個別設定只能設定允許的項目
    allowed_crawler_keys: set[str] = {'timeout', 'delay', 'ignore_extensions', 'retries'}
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

    # 聯集合併全域與個別的 ignore_extensions
    global_ignore_extensions: list[str] = global_crawler_config.get('ignore_extensions', [])
    local_ignore_extensions: list[str] = crawler_config.get('ignore_extensions', [])
    if global_ignore_extensions or local_ignore_extensions:
        # 移除重複的副檔名並轉回 list
        crawler_config['ignore_extensions'] = list(set(global_ignore_extensions + local_ignore_extensions))

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
    負責協調參數解析、設定讀取與爬蟲任務的建立或恢復。
    """
    args: argparse.Namespace | None = parse_args()
    if not args:
        return

    global_config: dict[str, Any] = {}
    try:
        global_config = load_config(args.global_config)
    except FileNotFoundError:
        logging.warning(f"找不到全域設定檔: {args.global_config}，將使用預設全域設定")
    except Exception as e:
        logging.error(f"讀取全域設定檔時發生錯誤: {e}")
        return

    setup_logging(global_config)

    db_url: str = global_config.get('db_url', 'sqlite:///db/crawler.db')
    manager: JobManager = JobManager(db_url=db_url)

    if args.list_jobs:
        jobs = manager.get_all_jobs()
        print("\n=== 爬蟲任務列表 ===")
        print(f"{'Job ID':<38} | {'Status':<10} | {'Created At':<20} | {'Start URL'}")
        print("-" * 100)
        for j in jobs:
            print(f"{j['id']:<38} | {j['status']:<10} | {j['created_at']:<20} | {j['start_url']}")
        print("====================\n")
        return

    if args.report:
        report = manager.get_job_report(args.report)
        if not report:
            logging.error(f"找不到指定的任務 ID: {args.report}")
            return
        
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
        print(f"  等待中 (Pending):   {report['queue']['pending']}")
        print(f"  已失敗 (Failed):    {report['queue']['failed']}")
        print("-" * 20)
        print("【產出成果】")
        print(f"  尋獲外部連結數: {report['external_links']}")
        print("====================\n")
        return

    if args.export:
        output_path = args.output if args.output else f"reports/{args.export}.csv"
        logging.info(f"準備將任務 {args.export} 匯出至 {output_path}...")
        success = manager.export_job_results(args.export, output_path)
        if success:
            logging.info("匯出成功！")
        return

    config: dict[str, Any] = {}
    if args.config:
        try:
            config = load_config(args.config)
        except FileNotFoundError:
            logging.error(f"找不到指定的設定檔: {args.config}")
            return
        except Exception as e:
            logging.error(f"讀取設定檔時發生錯誤: {e}")
            return

    crawler_config: dict[str, Any] = merge_and_validate_crawler_config(config, global_config)

    # 如果帶有 --resume 參數，則進行任務恢復
    if args.resume is not None:
        logging.info(f"正在恢復執行任務 {args.resume}...")
        manager.run_job(args.resume, crawler_config=crawler_config)
        return

    try:
        start_url: str | None = config.get('start_url')
        target_domains: list[str] = config.get('target_domains', [])
        internal_domains: list[str] = config.get('internal_domains', [])
        
        if not start_url:
            logging.error("設定檔中缺少必填參數: start_url")
            return
            
        logging.info("準備建立新任務...")
        job_id: str = manager.create_job(start_url, target_domains, internal_domains)
        logging.info(f"成功建立任務 {job_id}。爬蟲啟動中...")
        
        manager.run_job(job_id, crawler_config=crawler_config)
        
    except Exception as e:
        logging.error(f"啟動爬蟲時發生例外錯誤: {e}")

if __name__ == '__main__':
    main()
