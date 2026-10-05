"""建立初始管理員，並選用地匯入展示用巡檢資料。"""
import os

from sqlalchemy import select

from .auth import hash_password
from .common import new_id, utc_now
from .db import SessionLocal
from .models import InspectionItem, Location, LocationItem, User


def ensure_admin(session) -> bool:
    if session.scalar(select(User.id).limit(1)):
        return False
    now = utc_now()
    username = os.getenv("INSPECTION_ADMIN_USERNAME", "admin").strip().lower()
    password = os.getenv("INSPECTION_ADMIN_PASSWORD", "Admin@12345")
    display_name = os.getenv("INSPECTION_ADMIN_DISPLAY_NAME", "系統管理員").strip()
    session.add(User(id=new_id(), username=username, display_name=display_name,
                     password_hash=hash_password(password), role="system_admin", department="", email="",
                     is_active=True, must_change_password=True, failed_login_count=0, locked_until=None,
                     session_version=1, created_by=None, created_at=now, updated_at=now))
    session.commit()
    print(f"已建立初始管理員：{username}")
    if "INSPECTION_ADMIN_PASSWORD" not in os.environ:
        print("初始密碼：Admin@12345（登入後請立即修改）")
    return True


def main():
    with SessionLocal() as session:
        ensure_admin(session)
        if session.scalar(select(Location.id).limit(1)):
            print("已有地點資料，略過示範巡檢資料匯入。")
            return
        now = utc_now()
        locations = [
            Location(id=new_id(), code="LOC-001", name="一廠｜原料倉庫", area="一廠・1F",
                     description="原料存放及進出貨區域", is_active=True, created_at=now, updated_at=now),
            Location(id=new_id(), code="LOC-002", name="一廠｜生產線 A", area="一廠・2F",
                     description="包裝與生產設備區", is_active=True, created_at=now, updated_at=now),
            Location(id=new_id(), code="LOC-003", name="二廠｜消防通道", area="二廠・1F",
                     description="東側消防通道", is_active=True, created_at=now, updated_at=now),
            Location(id=new_id(), code="LOC-004", name="舊倉庫", area="一廠・B1",
                     description="已停止使用", is_active=False, created_at=now, updated_at=now),
        ]
        items = [
            InspectionItem(id=new_id(), code="CHK-001", name="消防通道保持暢通", category="消防安全",
                           description="確認通道無堆放物品、逃生動線可通行。", result_type="normal_abnormal_na",
                           is_active=True, created_at=now, updated_at=now),
            InspectionItem(id=new_id(), code="CHK-002", name="滅火器外觀與壓力正常", category="消防安全",
                           description="檢查壓力指針、有效期限及外觀。", result_type="normal_abnormal_na",
                           is_active=True, created_at=now, updated_at=now),
            InspectionItem(id=new_id(), code="CHK-003", name="地面無積水或油汙", category="環境衛生",
                           description="確認地面乾燥、無滑倒風險。", result_type="normal_abnormal_na",
                           is_active=True, created_at=now, updated_at=now),
            InspectionItem(id=new_id(), code="CHK-004", name="設備防護罩已固定", category="設備安全",
                           description="查看設備防護罩及固定螺絲。", result_type="normal_abnormal_na",
                           is_active=True, created_at=now, updated_at=now),
        ]
        session.add_all([*locations, *items])
        layout = [[0, 1, 2], [1, 2, 3], [0, 1], []]
        session.add_all(LocationItem(location_id=loc.id, item_id=items[item_index].id,
                                     sort_order=order, is_required=not (loc == locations[2] and order == 2))
                        for loc, indices in zip(locations, layout)
                        for order, item_index in enumerate(indices, start=1))
        session.commit()
    print("已建立 4 個示範地點及 4 個巡檢項目。")


if __name__ == "__main__":
    main()
