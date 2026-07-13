"""
任務資料備份與匯入服務。

提供匯出任務設定與結果資料為 JSON Lines (ZIP) 的功能，
以及將備份資料匯入並配發新擁有者的功能。
"""

import json
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime

from sqlalchemy.orm import Session

from crawler.models import CrawlQueue, ExternalLink, Job
from crawler.utils import (
    determine_external_link_status_category,
    determine_internal_link_status_category,
)

logger: logging.Logger = logging.getLogger(__name__)


# pylint: disable=too-many-locals
def export_job(db: Session, job_id: str, output_path: str) -> None:
    """
    匯出任務資料。

    將指定任務的元資料與佇列/外連結果以 JSON/JSONL 格式寫入輸出目錄中。
    若 output_path 以 .zip 結尾，將自動打包為 ZIP 壓縮檔。

    Args:
        db (Session): 資料庫 Session。
        job_id (str): 欲匯出的任務 ID。
        output_path (str): 匯出資料的目標資料夾路徑或 ZIP 檔案路徑。

    Raises:
        ValueError: 當找不到任務時拋出。
    """
    is_zip = output_path.lower().endswith(".zip")
    if is_zip:
        work_dir = tempfile.mkdtemp()
    else:
        work_dir = output_path
        os.makedirs(work_dir, exist_ok=True)

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"找不到任務 {job_id}")

        job_file = os.path.join(work_dir, "job_meta.json")
        job_data = {
            "start_url": job.start_url,
            "target_domains": job.target_domains,
            "trusted_domains": job.trusted_domains,
            "config_json": job.config_json,
            "status": job.status,
            "progress_stats": job.progress_stats,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        }
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(job_data, f, ensure_ascii=False, indent=2)

        logger.info("已匯出任務元資料至 %s", job_file)

        queue_file = os.path.join(work_dir, "crawl_queue.jsonl")
        queue_count = 0
        with open(queue_file, "w", encoding="utf-8") as f:
            for q in db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id).yield_per(2000):
                q_data = {
                    "url": q.url,
                    "source_url": q.source_url,
                    "status": q.status,
                    "status_code": q.status_code,
                    "retry_count": q.retry_count,
                    "depth": q.depth,
                    "error_message": q.error_message,
                    "status_category": q.status_category,
                    "is_secure": q.is_secure,
                    "created_at": q.created_at.isoformat(),
                    "updated_at": q.updated_at.isoformat(),
                }
                f.write(json.dumps(q_data, ensure_ascii=False) + "\n")
                queue_count += 1
        logger.info("已匯出 %d 筆佇列資料至 %s", queue_count, queue_file)

        ext_file = os.path.join(work_dir, "external_links.jsonl")
        ext_count = 0
        with open(ext_file, "w", encoding="utf-8") as f:
            for ext in db.query(ExternalLink).filter(ExternalLink.job_id == job_id).yield_per(2000):
                ext_data = {
                    "source_url": ext.source_url,
                    "target_url": ext.target_url,
                    "target_domain": ext.target_domain,
                    "ip_address": ext.ip_address,
                    "is_secure": ext.is_secure,
                    "http_status_code": ext.http_status_code,
                    "error_message": ext.error_message,
                    "status_category": ext.status_category,
                    "created_at": ext.created_at.isoformat(),
                    "updated_at": ext.updated_at.isoformat(),
                }
                f.write(json.dumps(ext_data, ensure_ascii=False) + "\n")
                ext_count += 1
        logger.info("已匯出 %d 筆外部連結資料至 %s", ext_count, ext_file)

        if is_zip:
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(job_file, "job_meta.json")
                if os.path.exists(queue_file):
                    zf.write(queue_file, "crawl_queue.jsonl")
                if os.path.exists(ext_file):
                    zf.write(ext_file, "external_links.jsonl")
            logger.info("已將任務備份壓縮至 %s", output_path)

    finally:
        if is_zip and os.path.exists(work_dir):
            shutil.rmtree(work_dir)


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def import_job(db: Session, input_path: str, new_user_id: str) -> None:
    """
    匯入任務資料。

    將存放於輸入目錄或 ZIP 檔中的 JSON/JSONL 資料寫入資料庫，並配發新的任務 ID 與指定新的擁有者。

    Args:
        db (Session): 資料庫 Session。
        input_path (str): 存放任務備份資料的來源資料夾路徑或 ZIP 檔案路徑。
        new_user_id (str): 接手該任務的新使用者 ID。

    Raises:
        ValueError: 當找不到任務元資料或解壓縮失敗時拋出。
    """
    is_zip = input_path.lower().endswith(".zip")
    if is_zip:
        work_dir = tempfile.mkdtemp()
        try:
            with zipfile.ZipFile(input_path, "r") as zf:
                zf.extractall(work_dir)
        except zipfile.BadZipFile as exc:
            shutil.rmtree(work_dir)
            raise ValueError(f"損壞的 ZIP 壓縮檔: {input_path}") from exc
    else:
        work_dir = input_path

    try:
        job_file = os.path.join(work_dir, "job_meta.json")
        queue_file = os.path.join(work_dir, "crawl_queue.jsonl")
        ext_file = os.path.join(work_dir, "external_links.jsonl")

        if not os.path.exists(job_file):
            raise ValueError(f"找不到任務元資料 {job_file}")

        with open(job_file, "r", encoding="utf-8") as f:
            job_data = json.load(f)

        new_job_id = str(uuid.uuid4())

        new_job = Job(
            id=new_job_id,
            user_id=new_user_id,
            start_url=job_data["start_url"],
            target_domains=job_data["target_domains"],
            trusted_domains=job_data["trusted_domains"],
            config_json=job_data["config_json"],
            status=job_data["status"],
            progress_stats=job_data.get("progress_stats"),
            created_at=datetime.fromisoformat(job_data["created_at"]),
            updated_at=datetime.fromisoformat(job_data.get("updated_at", job_data["created_at"])),
        )
        db.add(new_job)
        db.commit()
        logger.info("已建立新任務 %s (接手使用者: %s)", new_job_id, new_user_id)

        queue_stats = {"total": 0, "completed": 0, "warning": 0, "skipped": 0, "pending": 0, "failed": 0}
        ext_links_count = 0

        if os.path.exists(queue_file):
            queue_objects = []
            with open(queue_file, "r", encoding="utf-8") as f:
                for line in f:
                    q_data = json.loads(line)
                    
                    queue_stats["total"] += 1
                    q_status = q_data.get("status")
                    if q_status == "completed":
                        queue_stats["completed"] += 1
                    elif q_status == "warning":
                        queue_stats["warning"] += 1
                    elif q_status == "skip":
                        queue_stats["skipped"] += 1
                    elif q_status == "pending":
                        queue_stats["pending"] += 1
                    elif q_status == "failed":
                        queue_stats["failed"] += 1

                    queue_objects.append(
                        CrawlQueue(
                            job_id=new_job_id,
                            url=q_data["url"],
                            source_url=q_data["source_url"],
                            status=q_data["status"],
                            status_code=q_data["status_code"],
                            retry_count=q_data["retry_count"],
                            depth=q_data["depth"],
                            error_message=q_data["error_message"],
                            status_category=q_data.get("status_category")
                            or determine_internal_link_status_category(
                                q_data["status"], q_data["status_code"], q_data.get("error_message")
                            ),
                            is_secure=q_data.get("is_secure", True),
                            created_at=datetime.fromisoformat(q_data["created_at"]),
                            updated_at=datetime.fromisoformat(q_data.get("updated_at", q_data["created_at"])),
                        )
                    )
                    if len(queue_objects) >= 2000:
                        db.bulk_save_objects(queue_objects)
                        db.commit()
                        queue_objects = []
            if queue_objects:
                db.bulk_save_objects(queue_objects)
                db.commit()
            logger.info("佇列資料匯入完成")

        if os.path.exists(ext_file):
            ext_objects = []
            with open(ext_file, "r", encoding="utf-8") as f:
                for line in f:
                    ext_data = json.loads(line)
                    ext_links_count += 1
                    ext_objects.append(
                        ExternalLink(
                            job_id=new_job_id,
                            source_url=ext_data["source_url"],
                            target_url=ext_data["target_url"],
                            target_domain=ext_data.get("target_domain", ""),
                            ip_address=ext_data["ip_address"],
                            is_secure=ext_data["is_secure"],
                            http_status_code=ext_data["http_status_code"],
                            error_message=ext_data["error_message"],
                            status_category=ext_data.get("status_category")
                            or determine_external_link_status_category(
                                ext_data["ip_address"], ext_data["http_status_code"]
                            ),
                            created_at=datetime.fromisoformat(ext_data["created_at"]),
                            updated_at=datetime.fromisoformat(ext_data.get("updated_at", ext_data["created_at"])),
                        )
                    )
                    if len(ext_objects) >= 2000:
                        db.bulk_save_objects(ext_objects)
                        db.commit()
                        ext_objects = []
            if ext_objects:
                db.bulk_save_objects(ext_objects)
                db.commit()
            logger.info("外部連結資料匯入完成")

        if not job_data.get("progress_stats"):
            progress_dict = {
                "queue": queue_stats,
                "external_links": ext_links_count,
            }
            new_job.progress_stats = json.dumps(progress_dict)
            db.commit()
            logger.info("已為舊備份自動重建任務 %s 的進度統計 (progress_stats)", new_job_id)

    finally:
        if is_zip and os.path.exists(work_dir):
            shutil.rmtree(work_dir)
