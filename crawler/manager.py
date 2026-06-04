"""
爬蟲任務 (Job) 管理模組。

此模組提供 JobManager 類別，負責處理資料庫互動、建立爬蟲任務、
管理爬取佇列 (Queue)、處理中斷例外，以及執行主要的爬蟲迴圈。
"""

import logging
import os
import time
import csv
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session

from crawler.models import Base, Job, CrawlQueue, ExternalLink
from crawler.core import CrawlerCore
from crawler.utils import resolve_ip, get_domain
from typing import Any

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

        self.engine: Engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)
        self.SessionLocal: sessionmaker[Session] = sessionmaker(bind=self.engine)
        
    def create_job(self, start_url: str, target_domains: list[str], internal_domains: list[str]) -> str:
        """
        建立一個全新的爬蟲任務，並將起始網址加入到佇列中。

        Args:
            start_url (str): 準備進行爬取的起始網址。
            target_domains (list[str]): 允許爬蟲深入遍歷的網域陣列。
            internal_domains (list[str]): 被視為內部網站的網域陣列。

        Returns:
            str: 新建立任務的 ID。
        """
        with self.SessionLocal() as session:
            job: Job = Job(
                start_url=start_url,
                target_domains=','.join(target_domains),
                internal_domains=','.join(internal_domains),
                status='pending'
            )
            session.add(job)
            session.commit()
            
            # 將起始網址加入佇列
            queue_item: CrawlQueue = CrawlQueue(
                job_id=job.id,
                url=start_url,
                status='pending'
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

    def run_job(self, job_id: str, crawler_config: dict[str, Any] | None = None) -> None:
        """
        執行指定的爬蟲任務，直到佇列清空或遭到使用者中斷為止。

        Args:
            job_id (str): 欲執行的任務 ID。
            crawler_config (dict[str, Any] | None): 爬蟲相關的設定參數。
        """
        with self.SessionLocal() as session:
            job: Job | None = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error(f"找不到指定的任務 ID: {job_id}")
                return
                
            if job.status in ['completed', 'error']:
                logger.warning(f"任務 {job_id} 的狀態已經是 {job.status}，無法再次執行。")
                return
                
            job.status = 'running'
            session.commit()
            
            target_domains_list: list[str] = job.target_domains.split(',') if job.target_domains else []
            internal_domains_list: list[str] = job.internal_domains.split(',') if job.internal_domains else []
            
            if crawler_config is None:
                crawler_config = {}
            
            timeout: int = crawler_config.get('timeout', 30)
            delay: float = float(crawler_config.get('delay', 3.0))
            retries: int = crawler_config.get('retries', 3)
            ignore_extensions: list[str] | None = crawler_config.get('ignore_extensions')
            
            crawler: CrawlerCore = CrawlerCore(timeout=timeout, ignore_extensions=ignore_extensions)
            
            try:
                while True:
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
                    
                    try:
                        internal_links: list[str]
                        external_target_links: list[str]
                        internal_links, external_target_links = crawler.process_url(
                            current_url, target_domains_list, internal_domains_list
                        )
                        
                        # 若內部連結不在佇列中，則將其加入
                        for link in internal_links:
                            exists: CrawlQueue | None = session.query(CrawlQueue).filter(
                                CrawlQueue.job_id == job_id,
                                CrawlQueue.url == link
                            ).first()
                            if not exists:
                                new_item: CrawlQueue = CrawlQueue(job_id=job_id, url=link, status='pending')
                                session.add(new_item)
                                
                        # 處理找到的外部目標連結
                        for link in external_target_links:
                            # 避免同一個來源記錄重複的目標
                            exists_ext: ExternalLink | None = session.query(ExternalLink).filter(
                                ExternalLink.job_id == job_id,
                                ExternalLink.target_url == link
                            ).first()
                            
                            if not exists_ext:
                                # 解析 IP 位址
                                target_domain: str = get_domain(link)
                                ip: str | None = resolve_ip(target_domain) if target_domain else None
                                
                                new_ext: ExternalLink = ExternalLink(
                                    job_id=job_id,
                                    source_url=current_url,
                                    target_url=link,
                                    ip_address=ip
                                )
                                session.add(new_ext)
                                
                        queue_item.status = 'completed'
                        session.commit()
                        
                    except Exception as e:
                        if queue_item.retry_count < retries:
                            queue_item.retry_count += 1
                            logger.warning(f"處理網址 {current_url} 發生錯誤: {e}，將進行重試 (第 {queue_item.retry_count}/{retries} 次)")
                            session.commit()
                        else:
                            logger.error(f"處理網址 {current_url} 時發生錯誤且已達重試上限: {e}")
                            queue_item.status = 'failed'
                            queue_item.error_message = str(e)
                            session.commit()
                        
                    # 避免頻繁請求，加入短暫的延遲
                    time.sleep(delay)
                    
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

    def get_all_jobs(self) -> list[dict[str, Any]]:
        """
        取得所有任務的列表與基本資訊。
        """
        with self.SessionLocal() as session:
            jobs = session.query(Job).order_by(Job.created_at.desc()).all()
            return [
                {
                    'id': job.id,
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
                    'pending': pending,
                    'failed': failed
                },
                'external_links': total_external
            }

    def export_job_results(self, job_id: str, output_path: str) -> bool:
        """
        將指定任務收集到的外部連結匯出為 CSV 格式。
        """
        with self.SessionLocal() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error(f"找不到指定的任務 ID: {job_id}")
                return False

            links = session.query(ExternalLink).filter(ExternalLink.job_id == job_id).order_by(ExternalLink.created_at).all()
            
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            try:
                with open(output_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Source URL', 'Target URL', 'IP Address', 'Found At'])
                    for link in links:
                        writer.writerow([
                            link.source_url,
                            link.target_url,
                            link.ip_address if link.ip_address else '',
                            link.created_at.strftime('%Y-%m-%d %H:%M:%S')
                        ])
                return True
            except Exception as e:
                logger.error(f"匯出 CSV 時發生錯誤: {e}")
                return False
