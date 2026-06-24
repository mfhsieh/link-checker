"""
任務結果查詢的共用輔助模組。

提供動態欄位過濾、排序與 JSON 解析等共用邏輯。
"""

import json
import logging
from collections.abc import Callable

from sqlalchemy import asc, desc
from sqlalchemy.orm import Query

logger: logging.Logger = logging.getLogger(__name__)

ERROR_STATUS_FILTERS = [
    "dns_failed",
    "not_found",
    "server_error",
    "connection_error",
    "other_error",
    "blocked",
]


def _parse_json_list(val: object) -> list:
    """
    解析 JSON 字串為列表，用於反序列化資料庫聚合的 JSON 陣列。

    Args:
        val (object): JSON 字串或其他類型的值。

    Returns:
        list: 解析後的列表。
    """
    if isinstance(val, str):
        try:
            return json.loads(val) or []
        except json.JSONDecodeError:
            return []
    return list(val) if val else []


def _apply_col_filters(
    query: Query,
    col_filters_str: str | None,
    filter_map: dict[str, object],
    is_having: bool = False,
) -> Query:
    """
    動態套用欄位過濾器，減少主函式的區域變數與複雜度。

    Args:
        query (Query): SQLAlchemy 查詢物件。
        col_filters_str (str | None): JSON 格式的過濾字串。
        filter_map (dict[str, object]): 欄位對應的過濾條件函式。
        is_having (bool): 是否使用 having 而非 filter (預設 False)。

    Returns:
        Query: 套用過濾條件後的查詢物件。
    """
    if not col_filters_str:
        return query
    try:
        filters = json.loads(col_filters_str)
        for k, v in filters.items():
            if v and k in filter_map:
                cond = filter_map[k](str(v).lower())
                query = query.having(cond) if is_having else query.filter(cond)
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return query


def _apply_sorting(
    query: Query,
    sort_by: str | None,
    sort_asc: bool,
    sort_map: dict[str, object],
    default_sort: object,
) -> Query:
    """
    動態套用排序規則，減少主函式的區域變數與複雜度。

    Args:
        query (Query): SQLAlchemy 查詢物件。
        sort_by (str | None): 欲排序的欄位鍵名。
        sort_asc (bool): 是否為遞增排序。
        sort_map (dict[str, object]): 鍵名對應的欄位物件字典。
        default_sort (object): 預設排序規則。

    Returns:
        Query: 套用排序規則後的查詢物件。
    """
    if sort_by and sort_by in sort_map:
        order_func = asc if sort_asc else desc
        return query.order_by(order_func(sort_map[sort_by]))
    return query.order_by(default_sort)


# pylint: disable=too-many-arguments
def execute_paginated_query(
    query: Query,
    query_args: object,
    filter_map: dict[str, Callable],
    sort_map: dict[str, object],
    default_sort: object,
    row_mapper: Callable[[object], dict[str, object]],
    is_having: bool = False,
) -> dict[str, object]:
    """
    通用分頁查詢執行器，負責套用過濾、排序與分頁邏輯，並回傳固定格式的結果字典。

    Args:
        query (Query): SQLAlchemy 基礎查詢物件。
        query_args (object): 包含分頁與排序參數的資料類別 (例如 JobResultQuery)。
        filter_map (dict[str, Callable]): 欄位名稱對應的過濾函式。
        sort_map (dict[str, object]): 欄位名稱對應的排序物件。
        default_sort (object): 預設排序物件。
        row_mapper (Callable[[object], dict[str, object]]): 將單筆資料庫紀錄轉換為目標字典的函式。
        is_having (bool): 是否使用 having 過濾。

    Returns:
        dict[str, object]: 包含 items, total, page, page_size 等分頁資訊與資料的字典物件。
    """
    query = _apply_col_filters(query, query_args.col_filters, filter_map, is_having=is_having)
    query = _apply_sorting(query, query_args.sort_by, query_args.sort_asc, sort_map, default_sort)

    total = query.count()
    offset = (query_args.page - 1) * query_args.page_size
    items_list = [row_mapper(row) for row in query.offset(offset).limit(query_args.page_size).all()]

    total_pages = (total + query_args.page_size - 1) // query_args.page_size if total > 0 else 1
    return {
        "items": items_list,
        "total": total,
        "page": query_args.page,
        "page_size": query_args.page_size,
        "total_pages": total_pages,
    }
