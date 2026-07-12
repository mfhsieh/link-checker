"""
輕量級內部事件匯流排 (In-Memory Event Bus)。

提供系統內各個模組發布與訂閱事件的機制，用於解除模組間的直接相依性。
"""

import logging
from collections.abc import Callable
from enum import StrEnum

logger = logging.getLogger(__name__)


class SystemEvent(StrEnum):
    """系統內部事件名稱定義"""

    JOB_STATUS_CHANGED = "job_status_changed"
    USER_CLEANUP_FAILED = "user_cleanup_failed"
    USER_PERMANENTLY_DELETED = "user_permanently_deleted"
    USER_STATUS_CHANGED = "user_status_changed"
    USER_DELETED = "user_deleted"
    USER_ROLE_CHANGED = "user_role_changed"
    JOB_FORCE_ACTION = "job_force_action"
    CONFIG_CHANGE = "config_change"


# 註冊表：事件名稱 -> 處理函式列表
_subscribers: dict[str, list[Callable[..., object]]] = {}


def subscribe(event_name: SystemEvent | str, fn: Callable[..., object]) -> None:
    """
    訂閱特定的系統內部事件。

    將指定的處理常式 (handler) 註冊到對應的事件名稱上。
    當該事件被發布時，所有註冊的處理常式都會被依序同步呼叫。

    Args:
        event_name (SystemEvent | str): 欲訂閱的事件名稱。
        fn (Callable[..., object]): 當事件觸發時要執行的回呼函式。
    """
    event_key = str(event_name)
    if event_key not in _subscribers:
        _subscribers[event_key] = []
    _subscribers[event_key].append(fn)


def unsubscribe(event_name: SystemEvent | str, fn: Callable[..., object]) -> None:
    """
    取消訂閱特定的系統內部事件。

    將指定的處理常式 (handler) 從對應的事件名稱中移除。
    若該處理常式未曾訂閱或已移除，則忽略。

    Args:
        event_name (SystemEvent | str): 欲取消訂閱的事件名稱。
        fn (Callable[..., object]): 欲移除的回呼函式。
    """
    event_key = str(event_name)
    if event_key in _subscribers:
        try:
            _subscribers[event_key].remove(fn)
        except ValueError:
            pass
        if not _subscribers[event_key]:
            del _subscribers[event_key]


def publish(event_name: SystemEvent | str, **kwargs: object) -> None:
    """
    同步發布系統內部事件，並將 kwargs 參數傳遞給所有訂閱者。

    此函式會阻斷執行，直到所有相關的訂閱者處理完畢。
    如果單一訂閱者在執行過程中發生例外，錯誤會被攔截並記錄至日誌中，
    以確保不會因為單一元件的問題阻斷後續的事件通知或主流程。

    Args:
        event_name (SystemEvent | str): 欲發布的事件名稱。
        **kwargs (object): 傳遞給所有訂閱者的關鍵字參數。
    """
    event_key = str(event_name)
    logger.debug("發布事件: %s, 參數: %s", event_key, kwargs)
    for fn in _subscribers.get(event_key, []):
        try:
            fn(**kwargs)
        except Exception as e:  # pylint: disable=broad-exception-caught
            # 攔截並記錄錯誤，確保單一訂閱者的錯誤不會阻斷整體流程
            logger.error("事件 %s 處理器 %s 發生錯誤: %s", event_key, fn.__name__, e, exc_info=True)
