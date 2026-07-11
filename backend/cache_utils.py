"""
快取工具模組。
提供針對特定 API 結果的記憶體快取機制，以減輕後端伺服器的運算壓力。
"""

import hashlib
import json
from typing import Any, Callable, TypeVar

from cachetools import TTLCache

# API 快取常數設定：預設最多快取 500 個查詢結果，存活時間 300 秒（5 分鐘）
API_CACHE_MAXSIZE = 500
API_CACHE_TTL = 300

# 建立全域的任務查詢結果快取
job_results_cache = TTLCache(maxsize=API_CACHE_MAXSIZE, ttl=API_CACHE_TTL)

T = TypeVar("T")


# pylint: disable=too-many-arguments
def get_cached_job_result(
    job_status: str,
    job_updated_at: float,
    job_id: str,
    endpoint_name: str,
    params: dict[str, Any],
    compute_func: Callable[[], T],
) -> T:
    """
    獲取或計算快取結果。

    只有當任務狀態為 'completed' 或 'error' 時才會使用快取。

    Args:
        job_status (str): 任務的當前狀態 (例如 'pending', 'running', 'completed', 'error')。
        job_updated_at (float): 任務最後更新的時間戳記，確保任務重新探測後快取能立即失效。
        job_id (str): 任務 ID。
        endpoint_name (str): 區分不同 API 端點的名稱 (例如 'results_summary', 'job_diff')。
        params (dict[str, Any]): 影響查詢結果的參數字典。
        compute_func (Callable[[], T]): 若未命中快取時，用來產生結果的函式。

    Returns:
        T: 計算或快取的結果。
    """
    if job_status not in ("completed", "error"):
        return compute_func()

    # 確保參數的排序一致性，避免因為順序不同導致 hash 不同
    params_str = json.dumps(params, sort_keys=True, default=str)

    # 建立唯一的 cache key (加入 updated_at 確保任務更新時自動失效)
    key_str = f"{job_id}:{job_updated_at}:{endpoint_name}:{params_str}"
    cache_key = hashlib.md5(key_str.encode("utf-8")).hexdigest()

    if cache_key in job_results_cache:
        return job_results_cache[cache_key]

    result = compute_func()
    job_results_cache[cache_key] = result
    return result
