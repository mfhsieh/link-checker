"""
爬蟲任務 (Job) 管理模組。

此模組提供 JobManager 類別，負責處理資料庫互動、建立爬蟲任務、
管理爬取佇列 (Queue)、處理中斷例外，以及執行主要的爬蟲迴圈。
"""

import logging
import os
import time
import csv
import json
from sqlalchemy import create_engine, Engine, event, text
from sqlalchemy.orm import sessionmaker, Session

from crawler.models import Base, Job, CrawlQueue, ExternalLink
from crawler.core import CrawlerCore
from crawler.utils import resolve_ip, get_domain, is_in_domain_list
from typing import Any

def _get_domain_delay(url: str, domain_delays: dict[str, float], default_delay: float) -> float:
    domain = get_domain(url)
    if not domain:
        return default_delay
    domain = domain.lower()
    
    matched_delays = []
    for d, val in domain_delays.items():
        d_lower = d.lower()
        if domain == d_lower or domain.endswith('.' + d_lower):
            try:
                matched_delays.append((d_lower, float(val)))
            except (ValueError, TypeError):
                continue
            
    if not matched_delays:
        return default_delay
        
    matched_delays.sort(key=lambda x: len(x[0]), reverse=True)
    return matched_delays[0][1]

logger: logging.Logger = logging.getLogger(__name__)

class JobManager:
    """
    負責在資料庫中管理爬蟲任務與佇列狀態的管理器。

    Attributes:
        engine (Engine): SQLAlchemy 的資料庫引擎物件。
        SessionLocal (sessionmaker): 用來建立新 SQLAlchemy Session 的工廠 (Factory)。
    """

    def __init__(self, db_url: str = 'sqlite:///db/crawler.db') -> None:
        """
        初始化 Job 管理器並建立資料庫連線。

        Args:
            db_url (str): 資料庫的連線字串。預設為 'sqlite:///db/crawler.db'。
        """
        if db_url.startswith('sqlite:///'):
            db_path = db_url.replace('sqlite:///', '')
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

        connect_args = {}
        if db_url.startswith('sqlite:'):
            connect_args = {'timeout': 30}
        self.engine: Engine = create_engine(db_url, connect_args=connect_args, echo=False)
        if db_url.startswith('sqlite:'):
            @event.listens_for(self.engine, 'connect')
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA cache_size=10000")
                cursor.close()
        Base.metadata.create_all(self.engine)
        self.SessionLocal: sessionmaker[Session] = sessionmaker(bind=self.engine)
        
    def create_job(self, start_url: str, target_domains: list[str], internal_domains: list[str], crawler_config: dict[str, Any] | None = None, user_id: str | None = None) -> str:
        """
        建立一個全新的爬蟲任務，並將起始網址加入到佇列中。

        Args:
            start_url (str): 準備進行爬取的起始網址。
            target_domains (list[str]): 允許爬蟲深入遍歷的網域陣列。
            internal_domains (list[str]): 被視為內部網站的網域陣列。
            crawler_config (dict[str, Any] | None): (選填) 要寫入資料庫鎖定的爬蟲設定。
            user_id (str | None): (選填) 該任務的擁有者 ID。

        Returns:
            str: 新建立任務的 ID。
        """
        import json
        config_str: str | None = json.dumps(crawler_config) if crawler_config is not None else None
        
        with self.SessionLocal() as session:
            job: Job = Job(
                user_id=user_id,
                start_url=start_url,
                target_domains=','.join(target_domains),
                internal_domains=','.join(internal_domains),
                status='pending',
                config_json=config_str
            )
            session.add(job)
            session.commit()
            
            # 將起始網址加入佇列
            queue_item: CrawlQueue = CrawlQueue(
                job_id=job.id,
                url=start_url,
                source_url=None,
                status='pending',
                depth=0
            )
            session.add(queue_item)
            session.commit()
            
            return job.id
            
    def get_job(self, job_id: str) -> Job | None:
        """
        透過 ID 查詢並取得特定的任務物件。

        Args:
            job_id (str): 欲查詢的任務 ID。

        Returns:
            Job | None: 若找到對應的任務物件則回傳，否則回傳 None。
        """
        with self.SessionLocal() as session:
            return session.query(Job).filter(Job.id == job_id).first()

    def run_job(self, job_id: str, crawler_config: dict[str, Any] | None = None, force: bool = False) -> None:
        """
        執行指定的爬蟲任務，直到佇列清空或遭到使用者中斷為止。

        Args:
            job_id (str): 欲執行的任務 ID。
            crawler_config (dict[str, Any] | None): 爬蟲相關的設定參數。
            force (bool): 是否強制接管卡在 running 狀態的任務。
        """
        with self.SessionLocal() as session:
            job: Job | None = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error(f"找不到指定的任務 ID: {job_id}")
                return
                
            if job.status in ['completed', 'error']:
                logger.warning(f"任務 {job_id} 的狀態已經是 {job.status}，無法再次執行。")
                return
                
            if job.status == 'running' and not force:
                logger.error(f"任務 {job_id} 目前正在執行中。如果確定前次程序已經意外終止，請加上 -f 或 --force 參數強制接管任務。")
                return
                
            job.status = 'running'
            session.commit()
            
            target_domains_list: list[str] = job.target_domains.split(',') if job.target_domains else []
            internal_domains_list: list[str] = job.internal_domains.split(',') if job.internal_domains else []
            
            if crawler_config is None:
                # 代表從 Resume 恢復執行，需從資料庫讀取當時的設定檔
                import json
                if job.config_json:
                    try:
                        crawler_config = json.loads(job.config_json)
                        logger.info(f"已從資料庫成功載入任務 {job_id} 的專屬設定參數。")
                    except json.JSONDecodeError:
                        logger.error(f"任務 {job_id} 的設定檔解析失敗，將退回使用預設設定。")
                        crawler_config = {}
                else:
                    crawler_config = {}
            
            timeout: int = crawler_config.get('timeout', 30)
            delay: float = float(crawler_config.get('delay', 3.0))
            retries: int = crawler_config.get('retries', 3)
            ignore_extensions: list[str] | None = crawler_config.get('ignore_extensions')
            mime_type_filter: dict[str, Any] | None = crawler_config.get('mime_type_filter')
            ignore_regexes: list[str] | None = crawler_config.get('ignore_regexes')
            user_agent: str | None = crawler_config.get('user_agent')
            ssl_exempt_domains: list[str] | None = crawler_config.get('ssl_exempt_domains')
            domain_delays: dict[str, Any] = crawler_config.get('domain_delays', {})
            max_depth_val = crawler_config.get('max_depth')
            max_depth: int | None = int(max_depth_val) if max_depth_val is not None else None
            max_pages_val = crawler_config.get('max_pages')
            max_pages: int | None = int(max_pages_val) if max_pages_val is not None else None
            proxy_url: str | None = crawler_config.get('proxy_url')
            
            crawler: CrawlerCore = CrawlerCore(
                timeout=timeout, 
                ignore_extensions=ignore_extensions,
                mime_type_filter=mime_type_filter,
                ignore_regexes=ignore_regexes,
                user_agent=user_agent,
                ssl_exempt_domains=ssl_exempt_domains,
                proxy_url=proxy_url
            )
            
            # 統計該任務已發送實質請求的頁面數量
            crawled_count = session.query(CrawlQueue).filter(
                CrawlQueue.job_id == job_id,
                (CrawlQueue.status.in_(['completed', 'failed'])) | 
                ((CrawlQueue.status == 'skip') & (CrawlQueue.status_code != None))
            ).count()
            
            # 預熱外連快取：從資料庫中載入此任務已探測過的外連結果，避免重複請求
            checked_links_cache: dict[str, tuple[str | None, int | None, str | None]] = {}
            for ext in session.query(ExternalLink).filter(ExternalLink.job_id == job_id).all():
                if ext.http_status_code is not None or ext.error_message is not None:
                    checked_links_cache[ext.target_url] = (ext.ip_address, ext.http_status_code, ext.error_message)
            
            try:
                while True:
                    # 協同暫停檢查：確認任務狀態是否在外部被更改
                    session.expire(job)
                    current_job: Job | None = session.query(Job).filter(Job.id == job_id).first()
                    if not current_job or current_job.status != 'running':
                        logger.info(f"偵測到任務狀態變更為 {current_job.status if current_job else 'None'}，中斷爬取。")
                        break

                    if max_pages is not None and crawled_count >= max_pages:
                        logger.info(f"任務 {job_id} 已達到最大抓取頁數限制 ({max_pages})。優雅結束任務。")
                        job.status = 'completed'
                        session.commit()
                        break

                    # 從佇列中取得下一個等待處理的網址
                    queue_item: CrawlQueue | None = session.query(CrawlQueue).filter(
                        CrawlQueue.job_id == job_id,
                        CrawlQueue.status == 'pending'
                    ).first()
                    
                    if not queue_item:
                        logger.info(f"任務 {job_id} 已無等待中的網址。任務完成。")
                        job.status = 'completed'
                        session.commit()
                        break
                        
                    current_url: str = queue_item.url
                    logger.info(f"正在爬取: {current_url}")
                    
                    should_delay = True
                    try:
                        internal_links: list[str]
                        external_target_links: list[str]
                        status_code: int | None
                        status: str
                        request_sent: bool
                        internal_links, external_target_links, status_code, status, request_sent = crawler.process_url(
                            current_url, target_domains_list, internal_domains_list
                        )
                        
                        queue_item.status_code = status_code
                        
                        # 若內部連結不在佇列中，則將其加入
                        for link in internal_links:
                            new_depth = queue_item.depth + 1
                            if max_depth is not None and new_depth > max_depth:
                                continue
                            exists: CrawlQueue | None = session.query(CrawlQueue).filter(
                                CrawlQueue.job_id == job_id,
                                CrawlQueue.url == link
                            ).first()
                            if not exists:
                                new_item: CrawlQueue = CrawlQueue(
                                    job_id=job_id, 
                                    url=link, 
                                    source_url=current_url,
                                    status='pending',
                                    depth=new_depth
                                )
                                session.add(new_item)
                                
                        # 處理找到的外部目標連結
                        links_to_check = []
                        for link in external_target_links:
                            # 避免同一個來源記錄重複的目標
                            exists_ext = session.query(ExternalLink).filter(
                                ExternalLink.job_id == job_id,
                                ExternalLink.source_url == current_url,
                                ExternalLink.target_url == link
                            ).first()
                            
                            if not exists_ext:
                                links_to_check.append(link)

                        if links_to_check:
                            links_needing_http_check = []
                            for link in links_to_check:
                                if link in checked_links_cache:
                                    # 直接從快取取得結果，免除重複 DNS 與 HTTP 探測
                                    ip, status_code, err_msg = checked_links_cache[link]
                                    is_sec = link.lower().startswith('https://')
                                    new_ext = ExternalLink(
                                        job_id=job_id,
                                        source_url=current_url,
                                        target_url=link,
                                        ip_address=ip,
                                        is_secure=is_sec,
                                        http_status_code=status_code,
                                        error_message=err_msg
                                    )
                                    session.add(new_ext)
                                else:
                                    links_needing_http_check.append(link)

                            if links_needing_http_check:
                                # 並發處理實際需要進行探測的外部連結，最快提升檢測效能
                                from concurrent.futures import ThreadPoolExecutor
                                
                                def check_single_link(l):
                                    tgt_dom = get_domain(l)
                                    ip_res = resolve_ip(tgt_dom) if tgt_dom else None
                                    code_res, err_res = crawler.check_external_link(l)
                                    return l, ip_res, code_res, err_res

                                with ThreadPoolExecutor(max_workers=5) as executor:
                                    results = list(executor.map(check_single_link, links_needing_http_check))

                                for link, ip, status_code, err_msg in results:
                                    # 寫入快取供後續網頁共享
                                    checked_links_cache[link] = (ip, status_code, err_msg)
                                    
                                    is_sec = link.lower().startswith('https://')
                                    new_ext = ExternalLink(
                                        job_id=job_id,
                                        source_url=current_url,
                                        target_url=link,
                                        ip_address=ip,
                                        is_secure=is_sec,
                                        http_status_code=status_code,
                                        error_message=err_msg
                                    )
                                    session.add(new_ext)
                                
                        queue_item.status = status
                        session.commit()
                        
                        # 根據是否有發出請求決定是否延遲
                        should_delay = request_sent
                        if request_sent:
                            crawled_count += 1
                        
                    except Exception as e:
                        # 嘗試擷取 HTTP 狀態碼
                        import httpx
                        status_code = None
                        is_permanent_error = False
                        
                        if isinstance(e, httpx.HTTPStatusError):
                            status_code = e.response.status_code
                            queue_item.status_code = status_code
                            logger.error(f"抓取 {current_url} 時發生 HTTP 狀態碼錯誤 {status_code}")
                            
                            # 404 與 403 視為永久性錯誤
                            if status_code in (404, 403):
                                is_permanent_error = True
                        elif isinstance(e, httpx.RequestError):
                            queue_item.status_code = None
                            logger.error(f"抓取 {current_url} 時發生連線請求錯誤: {e}")
                        else:
                            queue_item.status_code = None
                            logger.error(f"抓取 {current_url} 時發生未預期例外: {e}")
                            
                        if is_permanent_error:
                            logger.error(f"網址 {current_url} 遭遇永久性錯誤 ({status_code})，直接標記為 failed，不進行重試。")
                            queue_item.status = 'failed'
                            queue_item.error_message = f"永久性錯誤: {e}"
                            session.commit()
                            crawled_count += 1
                        else:
                            if queue_item.retry_count < retries:
                                queue_item.retry_count += 1
                                current_domain_delay = _get_domain_delay(current_url, domain_delays, delay)
                                backoff_delay = current_domain_delay * (2 ** (queue_item.retry_count - 1))
                                logger.warning(f"處理網址 {current_url} 發生暫時性錯誤，將進行重試 (第 {queue_item.retry_count}/{retries} 次)。啟用指數退避延遲 {backoff_delay:.1f} 秒...")
                                session.commit()
                                time.sleep(backoff_delay)
                            else:
                                logger.error(f"處理網址 {current_url} 時發生錯誤且已達重試上限")
                                queue_item.status = 'failed'
                                queue_item.error_message = str(e)
                                session.commit()
                                crawled_count += 1
                        
                    # 避免頻繁請求，加入短暫的延遲
                    if should_delay:
                        current_domain_delay = _get_domain_delay(current_url, domain_delays, delay)
                        time.sleep(current_domain_delay)
                    
            except KeyboardInterrupt:
                logger.info(f"任務 {job_id} 已由使用者強制中斷。暫停任務中...")
                job_check: Job | None = session.query(Job).filter(Job.id == job_id).first()
                if job_check and job_check.status == 'running':
                    job_check.status = 'paused'
                    session.commit()
            except Exception as e:
                logger.error(f"任務 {job_id} 發生未預期例外: {e}")
                job_err: Job | None = session.query(Job).filter(Job.id == job_id).first()
                if job_err:
                    job_err.status = 'error'
                    session.commit()
            finally:
                crawler.close()

    def get_all_jobs(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """
        取得所有任務的列表與基本資訊。可透過 user_id 進行過濾。
        """
        with self.SessionLocal() as session:
            query = session.query(Job)
            if user_id:
                query = query.filter(Job.user_id == user_id)
            jobs = query.order_by(Job.created_at.desc()).all()
            return [
                {
                    'id': job.id,
                    'user_id': job.user_id,
                    'start_url': job.start_url,
                    'status': job.status,
                    'created_at': job.created_at.strftime('%Y-%m-%d %H:%M:%S')
                }
                for job in jobs
            ]

    def get_job_report(self, job_id: str) -> dict[str, Any] | None:
        """
        取得指定任務的詳細統計報告。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                return None

            total_queue = session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).count()
            completed = session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.status == 'completed').count()
            pending = session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.status == 'pending').count()
            failed = session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.status == 'failed').count()
            skipped = session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.status == 'skip').count()
            
            total_external = session.query(ExternalLink).filter(ExternalLink.job_id == job_id).count()

            return {
                'id': job.id,
                'start_url': job.start_url,
                'status': job.status,
                'created_at': job.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': job.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
                'queue': {
                    'total': total_queue,
                    'completed': completed,
                    'skipped': skipped,
                    'pending': pending,
                    'failed': failed
                },
                'external_links': total_external
            }

    def export_job_results(self, job_id: str, output_path: str, status_filter: str | None = None, export_group: bool = False) -> bool:
        """
        將指定任務收集到的外部連結匯出為 CSV 或 JSON 格式。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error(f"找不到指定的任務 ID: {job_id}")
                return False

            query = session.query(ExternalLink).filter(ExternalLink.job_id == job_id)
            
            # dead: DNS 解析失敗 (IP 位址為空)
            if status_filter == 'dead':
                query = query.filter((ExternalLink.ip_address == None) | (ExternalLink.ip_address == ''))
            # broken: HTTP 狀態碼 >= 400 或連線錯誤無狀態碼
            elif status_filter == 'broken':
                query = query.filter((ExternalLink.http_status_code >= 400) | (ExternalLink.http_status_code == None))

            links = query.order_by(ExternalLink.created_at).all()
            
            # unapproved 篩選 (不在 approved_domains 白名單中)
            if status_filter == 'unapproved':
                approved_domains = []
                if job.config_json:
                    try:
                        cfg = json.loads(job.config_json)
                        approved_domains = cfg.get('approved_domains', [])
                    except Exception:
                        pass
                
                filtered_links = []
                for link in links:
                    domain = get_domain(link.target_url)
                    if not domain or not is_in_domain_list(domain, approved_domains):
                        filtered_links.append(link)
                links = filtered_links

            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            is_json = output_path.lower().endswith('.json')

            try:
                if export_group:
                    # 聚合去重 (按 target_url 聚合)
                    from collections import defaultdict
                    agg_data = defaultdict(lambda: {
                        'ip': '',
                        'is_secure': True,
                        'status_code': None,
                        'error': '',
                        'count': 0,
                        'sources': set()
                    })
                    for link in links:
                        tgt = link.target_url
                        d = agg_data[tgt]
                        d['count'] += 1
                        d['sources'].add(link.source_url)
                        d['is_secure'] = link.is_secure
                        if link.ip_address and not d['ip']:
                            d['ip'] = link.ip_address
                        if link.http_status_code is not None and d['status_code'] is None:
                            d['status_code'] = link.http_status_code
                        if link.error_message and not d['error']:
                            d['error'] = link.error_message

                    if is_json:
                        json_data = []
                        for tgt, d in agg_data.items():
                            json_data.append({
                                'target_url': tgt,
                                'ip_address': d['ip'] if d['ip'] else None,
                                'is_secure': d['is_secure'],
                                'http_status_code': d['status_code'],
                                'error_message': d['error'] if d['error'] else None,
                                'occurrence_count': d['count'],
                                'source_urls': sorted(list(d['sources']))
                            })
                        with open(output_path, 'w', encoding='utf-8') as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=2)
                    else:
                        with open(output_path, 'w', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow(['Target URL', 'IP Address', 'Is Secure', 'HTTP Status Code', 'Error Message', 'Occurrence Count', 'Source URLs'])
                            for tgt, d in agg_data.items():
                                writer.writerow([
                                    tgt,
                                    d['ip'],
                                    d['is_secure'],
                                    d['status_code'] if d['status_code'] is not None else '',
                                    d['error'],
                                    d['count'],
                                    ', '.join(sorted(list(d['sources'])))
                                ])
                else:
                    # 一般平鋪導出 (不聚合)
                    if is_json:
                        json_data = []
                        for link in links:
                            json_data.append({
                                'source_url': link.source_url,
                                'target_url': link.target_url,
                                'ip_address': link.ip_address if link.ip_address else None,
                                'is_secure': link.is_secure,
                                'http_status_code': link.http_status_code,
                                'error_message': link.error_message if link.error_message else None,
                                'created_at': link.created_at.strftime('%Y-%m-%d %H:%M:%S')
                            })
                        with open(output_path, 'w', encoding='utf-8') as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=2)
                    else:
                        with open(output_path, 'w', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow(['Source URL', 'Target URL', 'IP Address', 'Is Secure', 'HTTP Status Code', 'Error Message', 'Found At'])
                            for link in links:
                                writer.writerow([
                                    link.source_url,
                                    link.target_url,
                                    link.ip_address if link.ip_address else '',
                                    link.is_secure,
                                    link.http_status_code if link.http_status_code is not None else '',
                                    link.error_message if link.error_message else '',
                                    link.created_at.strftime('%Y-%m-%d %H:%M:%S')
                                ])
                return True
            except Exception as e:
                logger.error(f"匯出檔案時發生錯誤: {e}")
                return False

    def pause_job(self, job_id: str) -> bool:
        """
        將指定任務狀態更新為 paused（僅在任務當前為 running 時允許）。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error(f"找不到指定的任務 ID: {job_id}")
                return False
            if job.status == 'running':
                job.status = 'paused'
                session.commit()
                return True
            logger.warning(f"任務 {job_id} 當前狀態為 {job.status}，非 running，無法暫停。")
            return False

    def delete_job(self, job_id: str) -> bool:
        """
        刪除指定任務，並利用級聯刪除 (Cascade Delete) 機制清理其所有佇列與外連結果。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error(f"找不到指定的任務 ID: {job_id}")
                return False
            session.delete(job)
            session.commit()
            return True

    def reset_job(self, job_id: str) -> bool:
        """
        重設指定任務：將任務狀態設回 pending，清除已發生的外連記錄，重置佇列。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error(f"找不到指定的任務 ID: {job_id}")
                return False
            
            job.status = 'pending'
            
            # 清除外連記錄
            session.query(ExternalLink).filter(ExternalLink.job_id == job_id).delete()
            
            # 清除佇列中除起始網址外的所有記錄
            session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.url != job.start_url).delete()
            
            # 重設起始網址的佇列狀態
            start_queue = session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.url == job.start_url).first()
            if start_queue:
                start_queue.status = 'pending'
                start_queue.retry_count = 0
                start_queue.status_code = None
                start_queue.error_message = None
            else:
                new_start = CrawlQueue(
                    job_id=job_id,
                    url=job.start_url,
                    source_url=None,
                    status='pending'
                )
                session.add(new_start)
                
            session.commit()
            return True
