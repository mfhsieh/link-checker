"""
密碼雜湊工具模組。

使用 passlib 的 bcrypt 後端進行密碼雜湊與驗證。
嚴禁使用 MD5、SHA-1 等弱雜湊演算法。
"""

import re

import bcrypt

# 密碼強度規則
_MIN_LENGTH: int = 12
_COMPLEXITY_PATTERNS: list[re.Pattern] = [
    re.compile(r"[A-Z]"),  # 大寫字母
    re.compile(r"[a-z]"),  # 小寫字母
    re.compile(r"[0-9]"),  # 數字
    re.compile(r"[^A-Za-z0-9]"),  # 特殊符號
]
_MIN_COMPLEXITY_CLASSES: int = 3


def hash_password(plain_password: str) -> str:
    """
    使用 bcrypt 對純文字密碼進行雜湊。

    Args:
        plain_password (str): 純文字密碼。

    Returns:
        str: bcrypt 雜湊字串。
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    驗證純文字密碼與 bcrypt 雜湊是否相符。

    Args:
        plain_password (str): 使用者輸入的純文字密碼。
        hashed_password (str): 資料庫中儲存的 bcrypt 雜湊值。

    Returns:
        bool: 若相符回傳 True，否則回傳 False。
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str, email: str) -> list[str]:
    """
    驗證密碼是否符合安全強度標準。

    規則：
    - 長度至少 12 個字元
    - 至少包含大寫字母、小寫字母、數字、特殊符號中的三類
    - 不得與電子郵件本地端（@ 前面的部分）相同或包含之

    Args:
        password (str): 欲驗證的密碼。
        email (str): 使用者的電子郵件（用於禁用規則比對）。

    Returns:
        list[str]: 不符合規則的錯誤訊息清單。若清單為空則表示密碼強度合格。
    """
    errors: list[str] = []

    if len(password) < _MIN_LENGTH:
        errors.append(f"密碼長度至少需要 {_MIN_LENGTH} 個字元。")

    matched_classes = sum(1 for pattern in _COMPLEXITY_PATTERNS if pattern.search(password))
    if matched_classes < _MIN_COMPLEXITY_CLASSES:
        errors.append(f"密碼需包含大寫字母、小寫字母、數字、特殊符號中的至少 {_MIN_COMPLEXITY_CLASSES} 類。")

    # 提取 email 本地端（@ 前面的部分）並進行相似度比對
    local_part = email.split("@")[0].lower() if "@" in email else email.lower()
    if local_part and (local_part in password.lower() or password.lower() in local_part):
        errors.append("密碼不得與電子郵件帳號相同或包含電子郵件的本地端部分。")

    return errors
