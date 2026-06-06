import os
import sys
import secrets
import string

# 將專案根目錄加入 sys.path，以便載入 backend 模組
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.auth.db import get_auth_session_local
from backend.auth.models import User
from backend.auth.password import hash_password

def generate_random_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        password = ''.join(secrets.choice(alphabet) for i in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and sum(c.isdigit() for c in password) >= 3):
            return password

def create_admin(email: str):
    SessionLocal = get_auth_session_local()
    with SessionLocal() as db:
        existing = db.query(User).filter(User.email == email).first()
        random_password = generate_random_password()
        
        if existing:
            print(f"使用者 {email} 已存在，將更新其密碼並設為管理員，狀態重置為待設密。")
            existing.password_hash = hash_password(random_password)
            existing.role = "admin"
            existing.status = "pending"
        else:
            user = User(
                email=email,
                password_hash=hash_password(random_password),
                role="admin",
                status="pending"
            )
            db.add(user)
        db.commit()
        print(f"成功設定管理員帳號：{email}")
        print(f"============================================================")
        print(f"系統產生的初始隨機密碼：{random_password}")
        print(f"請使用此密碼進行首次登入，並依照系統要求重新設定安全密碼。")
        print(f"============================================================")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="建立或更新管理員帳號")
    parser.add_argument("email", help="管理員 Email")
    args = parser.parse_args()
    
    create_admin(args.email)
