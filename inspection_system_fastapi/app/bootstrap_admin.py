"""啟動前確保系統至少有一個可登入的管理員。"""
from .db import SessionLocal
from .seed import ensure_admin


def main():
    with SessionLocal() as session:
        if not ensure_admin(session):
            print("管理員帳號已存在。")


if __name__ == "__main__":
    main()
