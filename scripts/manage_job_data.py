"""
任務資料備份與匯入工具。

本腳本為命令列介面，主要邏輯已移至 backend.jobs.services.backup 中。
"""

import argparse
import logging
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 將專案根目錄加入 PYTHONPATH
PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# pylint: disable=wrong-import-position
from backend.config import get_settings  # noqa: E402
from backend.jobs.services.backup import export_job, import_job  # noqa: E402

# pylint: enable=wrong-import-position

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger: logging.Logger = logging.getLogger("job_sync")


def main() -> None:
    """
    解析指令並執行對應操作。

    使用 argparse 讀取命令列參數，根據指定的操作 (export 或 import)
    將參數與資料庫連線導向至 backend 的備份服務處理。

    Raises:
        SystemExit: 當命令列參數解析錯誤、發生例外或缺少必填參數時拋出。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["export", "import"])
    parser.add_argument("arg1")
    parser.add_argument("arg2")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.CRAWLER_DB_URL)
    session_factory = sessionmaker(bind=engine)

    try:
        with session_factory() as db:
            if args.command == "export":
                export_job(db, args.arg1, args.arg2)
            elif args.command == "import":
                import_job(db, args.arg1, args.arg2)
    except Exception as e:  # pylint: disable=broad-except
        logger.error(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
