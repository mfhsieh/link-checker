"""
稽核日誌服務模組。

此模組負責訂閱各種系統級別的關鍵操作事件（如帳號刪除、任務接管、設定變更），
並統一將稽核紀錄寫入 AuthLog 資料庫表，以供日後安全追蹤與查閱。

模組主要職責：
- 註冊並監聽事件匯流排中的高風險操作事件
- 安全地開啟獨立的資料庫工作階段進行紀錄寫入
- 捕捉並記錄寫入失敗的例外狀況，避免干擾主要業務流程
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
    內部事件處理常式：接收事件資料並寫入 AuthLog。

    當訂閱的系統事件被觸發時，此函式會被呼叫。它會開啟獨立的 Auth 資料庫 Session，
    將事件詳細資訊寫入 AuthLog，若發生資料庫連線或寫入錯誤，將捕捉並輸出嚴重層級的日誌，
    以避免中斷觸發該事件的上游業務流程。

    Args:
        event_type (str): 事件名稱（如 'user_deleted'）。
        user_id (str | None): 操作者的 User ID（若適用）。
        ip_address (str | None): 客戶端的來源 IP。
        detail (str | None): 補充的詳細資訊（通常是格式化後的 JSON 字串）。
        **kwargs (object): 用於攔截並忽略其他由發布者傳入但用不到的多餘參數。
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
    註冊系統級別操作的稽核事件監聽器。

    此函式應於系統啟動時被呼叫，負責訂閱所有關鍵的系統事件（如使用者刪除、
    全域設定變更、任務強制接管與角色異動等），並將它們與內部處理常式 `_handle_audit_event` 進行綁定。
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
