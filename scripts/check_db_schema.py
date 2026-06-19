# pylint: disable=wrong-import-position, import-error
# ruff: noqa: E402
"""資料庫架構檢驗工具。

此腳本讀取 `.env` 中的 `AUTH_DB_URL` 與 `CRAWLER_DB_URL` 設定，
利用 SQLAlchemy Inspection 機制反射資料庫結構，
並與程式定義的 ORM Metadata (AuthBase, Base) 進行比對，
列出缺失的資料表、欄位、索引或外鍵約束。
"""

import logging
import os
import sys

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import MetaData

# 將專案根目錄加入 PYTHONPATH
PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend.auth.models import AuthBase
from backend.config import get_settings
from crawler.models import Base

# 初始化日誌
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger("schema-check")


# pylint: disable=too-many-locals, too-many-branches
def compare_metadata_with_db(engine: Engine, metadata: MetaData, db_name: str) -> bool:
    """比對指定的 ORM Metadata 與資料庫真實 Schema 差異。

    Args:
        engine (Engine): SQLAlchemy 資料庫引擎。
        metadata (MetaData): 程式定義的 ORM Metadata。
        db_name (str): 資料庫識別名稱（如 "Auth DB" 或 "Crawler DB"）。

    Returns:
        bool: 若完全一致回傳 True，有任何差異則回傳 False。
    """
    logger.info("=== 開始檢查 %s 架構 ===", db_name)
    inspector = inspect(engine)

    # 取得真實與預期的 Table 清單
    db_tables = set(inspector.get_table_names())
    expected_tables = set(metadata.tables.keys())

    has_diff: bool = False

    # 1. 檢查缺失的資料表
    missing_tables = expected_tables - db_tables
    if missing_tables:
        logger.error("[%s] 缺失以下資料表: %s", db_name, missing_tables)
        has_diff = True

    # 對於存在的資料表，深入比對 Columns 與 Indexes
    for table_name in expected_tables:
        if table_name in missing_tables:
            continue

        table_obj = metadata.tables[table_name]

        # A. 檢查 Columns
        db_cols = {col["name"]: col for col in inspector.get_columns(table_name)}
        expected_cols = table_obj.columns

        for col_name, col_obj in expected_cols.items():
            if col_name not in db_cols:
                logger.error("[%s] 資料表 %s 缺失欄位: %s", db_name, table_name, col_name)
                has_diff = True
            else:
                db_type = str(db_cols[col_name]["type"]).lower()
                expected_type = str(col_obj.type).lower()
                # 由於不同 DB 的對應型別字面可能會有些許差異，此處進行前置比對與簡單轉換
                db_type_base = db_type.split("(", maxsplit=1)[0]
                expected_type_base = expected_type.split("(", maxsplit=1)[0]
                type_aliases = {
                    "boolean": "bool",
                    "bool": "boolean",
                    "timestamp": "datetime",
                    "datetime": "timestamp",
                }
                if db_type_base != expected_type_base:
                    if type_aliases.get(db_type_base) != expected_type_base:
                        logger.warning(
                            "[%s] 資料表 %s 欄位 %s 型別可能不一致: 預期為 %s，資料庫中為 %s",
                            db_name,
                            table_name,
                            col_name,
                            expected_type,
                            db_type,
                        )

        # B. 檢查 Indexes
        db_indexes = {idx["name"]: idx for idx in inspector.get_indexes(table_name)}
        expected_indexes = {idx.name: idx for idx in table_obj.indexes}

        for idx_name in expected_indexes:
            if idx_name not in db_indexes:
                logger.error("[%s] 資料表 %s 缺失索引: %s", db_name, table_name, idx_name)
                has_diff = True

        # C. 檢查 Foreign Keys (僅在能取得外鍵資訊時檢查)
        db_fks = inspector.get_foreign_keys(table_name)
        for fk_obj in table_obj.foreign_keys:
            target_table = fk_obj.column.table.name
            target_col = fk_obj.column.name
            local_col = fk_obj.parent.name

            found: bool = False
            for db_fk in db_fks:
                if (
                    db_fk["referred_table"] == target_table
                    and target_col in db_fk["referred_columns"]
                    and local_col in db_fk["constrained_columns"]
                ):
                    found = True
                    break
            if not found:
                logger.error(
                    "[%s] 資料表 %s 缺失外鍵約束: %s -> %s(%s)",
                    db_name,
                    table_name,
                    local_col,
                    target_table,
                    target_col,
                )
                has_diff = True

    if not has_diff:
        logger.info("[%s] 結構檢查完成：完全符合程式預期！\n", db_name)
    else:
        logger.error("[%s] 結構檢查完成：偵測到 Schema 不一致！\n", db_name)

    return not has_diff


def main() -> None:
    """主控制流程。"""
    settings = get_settings()

    auth_url = settings.AUTH_DB_URL
    crawler_url = settings.CRAWLER_DB_URL

    logger.info("========================================")
    logger.info("  正在檢驗生產環境資料庫架構 (Schema Check) ")
    logger.info("========================================")
    logger.info("Auth DB URL      : %s", auth_url.split("@")[-1])
    logger.info("Crawler DB URL   : %s", crawler_url.split("@")[-1])
    logger.info("========================================")

    auth_engine = create_engine(auth_url)
    crawler_engine = create_engine(crawler_url)

    auth_ok = compare_metadata_with_db(auth_engine, AuthBase.metadata, "Auth DB")
    crawler_ok = compare_metadata_with_db(crawler_engine, Base.metadata, "Crawler DB")

    if auth_ok and crawler_ok:
        logger.info("所有資料庫架構檢驗完成，皆與程式 ORM 定義完全相符。")
        sys.exit(0)
    else:
        logger.error("錯誤：資料庫架構與程式 ORM 定義不一致，請參考上述錯誤日誌進行修正。")
        sys.exit(1)


if __name__ == "__main__":
    main()
