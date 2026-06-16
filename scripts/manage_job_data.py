"""
任務資料備份與匯入工具。

以 JSON Lines 格式匯出/匯入任務設定與結果資料，以支援跨資料庫（如 SQLite 到 PostgreSQL）的遷移，
並在匯入時自動配發新的任務 ID 與指定新的擁有者。
"""

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime

# 將專案根目錄加入 PYTHONPATH
PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# pylint: disable=wrong-import-position
# isort: off
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.config import get_settings  # noqa: E402
from crawler.models import CrawlQueue, ExternalLink, Job  # noqa: E402
# isort: on

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger: logging.Logger = logging.getLogger("job_sync")


def export_job(job_id: str, output_dir: str) -> None:
    """
    匯出任務資料。

    將指定任務的元資料與佇列/外連結果以 JSON/JSONL 格式寫入輸出目錄中。

    Args:
        job_id (str): 欲匯出的任務 ID。
        output_dir (str): 匯出資料的目標資料夾路徑。

    Raises:
        SystemExit: 當找不到任務時，結束程式。
    """
    settings = get_settings()
    engine = create_engine(settings.CRAWLER_DB_URL)
    session_factory = sessionmaker(bind=engine)

    os.makedirs(output_dir, exist_ok=True)

    with session_factory() as db:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("找不到任務 %s", job_id)
            sys.exit(1)

        job_file = os.path.join(output_dir, "job_meta.json")
        job_data = {
            "start_url": job.start_url,
            "target_domains": job.target_domains,
            "trusted_domains": job.trusted_domains,
            "config_json": job.config_json,
            "status": job.status,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        }
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(job_data, f, ensure_ascii=False, indent=2)

        logger.info("已匯出任務元資料至 %s", job_file)

        # 匯出 CrawlQueue (採 JSONL 格式以防 OOM)
        queue_file = os.path.join(output_dir, "crawl_queue.jsonl")
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
                    "created_at": q.created_at.isoformat(),
                    "updated_at": q.updated_at.isoformat(),
                }
                f.write(json.dumps(q_data, ensure_ascii=False) + "\n")
                queue_count += 1
        logger.info("已匯出 %d 筆佇列資料至 %s", queue_count, queue_file)

        # 匯出 ExternalLink (採 JSONL 格式以防 OOM)
        ext_file = os.path.join(output_dir, "external_links.jsonl")
        ext_count = 0
        with open(ext_file, "w", encoding="utf-8") as f:
            for ext in db.query(ExternalLink).filter(ExternalLink.job_id == job_id).yield_per(2000):
                ext_data = {
                    "source_url": ext.source_url,
                    "target_url": ext.target_url,
                    "ip_address": ext.ip_address,
                    "is_secure": ext.is_secure,
                    "http_status_code": ext.http_status_code,
                    "error_message": ext.error_message,
                    "created_at": ext.created_at.isoformat(),
                }
                f.write(json.dumps(ext_data, ensure_ascii=False) + "\n")
                ext_count += 1
        logger.info("已匯出 %d 筆外部連結資料至 %s", ext_count, ext_file)


def import_job(input_dir: str, new_user_id: str) -> None:
    """
    匯入任務資料。

    將存放於輸入目錄中的 JSON/JSONL 資料寫入資料庫，並配發新的任務 ID 與指定新的擁有者。

    Args:
        input_dir (str): 存放任務備份資料的來源資料夾路徑。
        new_user_id (str): 接手該任務的新使用者 ID。

    Raises:
        SystemExit: 當找不到任務元資料時，結束程式。
    """
    settings = get_settings()
    engine = create_engine(settings.CRAWLER_DB_URL)
    session_factory = sessionmaker(bind=engine)

    job_file = os.path.join(input_dir, "job_meta.json")
    queue_file = os.path.join(input_dir, "crawl_queue.jsonl")
    ext_file = os.path.join(input_dir, "external_links.jsonl")

    if not os.path.exists(job_file):
        logger.error("找不到任務元資料 %s", job_file)
        sys.exit(1)

    with open(job_file, "r", encoding="utf-8") as f:
        job_data = json.load(f)

    new_job_id = str(uuid.uuid4())

    with session_factory() as db:
        new_job = Job(
            id=new_job_id,
            user_id=new_user_id,
            start_url=job_data["start_url"],
            target_domains=job_data["target_domains"],
            trusted_domains=job_data["trusted_domains"],
            config_json=job_data["config_json"],
            status=job_data["status"],
            created_at=datetime.fromisoformat(job_data["created_at"]),
            updated_at=datetime.fromisoformat(job_data["updated_at"]),
        )
        db.add(new_job)
        db.commit()
        logger.info("已建立新任務 %s (接手使用者: %s)", new_job_id, new_user_id)

        if os.path.exists(queue_file):
            queue_objects = []
            with open(queue_file, "r", encoding="utf-8") as f:
                for line in f:
                    q_data = json.loads(line)
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
                            created_at=datetime.fromisoformat(q_data["created_at"]),
                            updated_at=datetime.fromisoformat(q_data["updated_at"]),
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
                    ext_objects.append(
                        ExternalLink(
                            job_id=new_job_id,
                            source_url=ext_data["source_url"],
                            target_url=ext_data["target_url"],
                            ip_address=ext_data["ip_address"],
                            is_secure=ext_data["is_secure"],
                            http_status_code=ext_data["http_status_code"],
                            error_message=ext_data["error_message"],
                            created_at=datetime.fromisoformat(ext_data["created_at"]),
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


def main() -> None:
    """
    解析指令並執行對應操作。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["export", "import"])
    parser.add_argument("arg1")
    parser.add_argument("arg2")
    args = parser.parse_args()
    if args.command == "export":
        export_job(args.arg1, args.arg2)
    elif args.command == "import":
        import_job(args.arg1, args.arg2)


if __name__ == "__main__":
    main()
