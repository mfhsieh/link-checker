"""
稽核日誌服務模組。

負責訂閱各種系統操作事件（如帳號刪除、任務接管、設定變更），
並統一將稽核紀錄寫入 AuthLog 資料表。
"""

import logging
from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError

from backend.auth.db import get_auth_session_local
from backend.auth.models import AuthLog
from backend.events import SystemEvent, subscribe

logger: logging.Logger = logging.getLogger(__name__)


def _handle_audit_event(
    event_type: str,
    user_id: str | None = None,
    ip_address: str | None = None,
    detail: str | None = None,
    **kwargs: object,  # pylint: disable=unused-argument
) -> None:
    """
    內部處理函式：接收事件並寫入 AuthLog。

    Args:
        event_type (str): 事件名稱（如 'user_deleted'）。
        user_id (str | None): 操作者的 User ID。
        ip_address (str | None): 客戶端 IP。
        detail (str | None): 補充詳細資訊（通常是 JSON 字串）。
        kwargs: 攔截其他多餘參數。
    """
    try:
        session_factory = get_auth_session_local()
        with session_factory() as auth_db:
            auth_log = AuthLog(
                user_id=user_id,
                event_type=event_type,
                ip_address=ip_address,
                detail=detail,
            )
            auth_db.add(auth_log)
            auth_db.commit()
    except SQLAlchemyError as e:
        logger.critical("[AUDIT_LOG_FAILURE] 寫入稽核日誌失敗 [%s]: %s", event_type, e, exc_info=True)
    except Exception as e:  # pylint: disable=broad-except
        logger.critical("[AUDIT_LOG_FAILURE] 處理稽核日誌事件時發生未預期錯誤 [%s]: %s", event_type, e, exc_info=True)


def subscribe_to_audit_events() -> None:
    """
    註冊稽核日誌的事件監聽。
    """
    audit_events = [
        SystemEvent.USER_DELETED,
        SystemEvent.CONFIG_CHANGE,
        SystemEvent.JOB_FORCE_ACTION,
        SystemEvent.USER_STATUS_CHANGED,
        SystemEvent.USER_ROLE_CHANGED,
    ]

    for event_name in audit_events:
        # 使用 closure 捕捉 event_name，避免迴圈變數延遲綁定問題
        def make_handler(evt: str) -> Callable[..., None]:
            return lambda **kwargs: _handle_audit_event(event_type=evt, **kwargs)

        subscribe(event_name, make_handler(event_name))
        logger.info("已註冊稽核事件監聽器: %s", event_name)
