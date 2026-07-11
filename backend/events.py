"""
輕量級內部事件匯流排 (In-Memory Event Bus)。

提供系統內各個模組發布與訂閱事件的機制，用於解除模組間的直接相依性。
"""

import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

# 註冊表：事件名稱 -> 處理函式列表
_subscribers: Dict[str, List[Callable[..., Any]]] = {}


def subscribe(event_name: str, fn: Callable[..., Any]) -> None:
    """
    訂閱特定的系統內部事件。

    將指定的處理常式 (handler) 註冊到對應的事件名稱上。
    當該事件被發布時，所有註冊的處理常式都會被依序同步呼叫。

    Args:
        event_name (str): 欲訂閱的事件名稱。
        fn (Callable[..., Any]): 當事件觸發時要執行的回呼函式。
    """
    if event_name not in _subscribers:
        _subscribers[event_name] = []
    _subscribers[event_name].append(fn)


def unsubscribe(event_name: str, fn: Callable[..., Any]) -> None:
    """
    取消訂閱特定的系統內部事件。

    將指定的處理常式 (handler) 從對應的事件名稱中移除。
    若該處理常式未曾訂閱或已移除，則忽略。

    Args:
        event_name (str): 欲取消訂閱的事件名稱。
        fn (Callable[..., Any]): 欲移除的回呼函式。
    """
    if event_name in _subscribers:
        try:
            _subscribers[event_name].remove(fn)
        except ValueError:
            pass
        if not _subscribers[event_name]:
            del _subscribers[event_name]


def publish(event_name: str, **kwargs: Any) -> None:
    """
    同步發布系統內部事件，並將 kwargs 參數傳遞給所有訂閱者。

    此函式會阻斷執行，直到所有相關的訂閱者處理完畢。
    如果單一訂閱者在執行過程中發生例外，錯誤會被攔截並記錄至日誌中，
    以確保不會因為單一元件的問題阻斷後續的事件通知或主流程。

    Args:
        event_name (str): 欲發布的事件名稱。
        **kwargs (Any): 傳遞給所有訂閱者的關鍵字參數。
    """
    logger.debug("發布事件: %s, 參數: %s", event_name, kwargs)
    for fn in _subscribers.get(event_name, []):
        try:
            fn(**kwargs)
        except Exception as e:  # pylint: disable=broad-exception-caught
            # 攔截並記錄錯誤，確保單一訂閱者的錯誤不會阻斷整體流程
            logger.error("事件 %s 處理器 %s 發生錯誤: %s", event_name, fn.__name__, e, exc_info=True)
