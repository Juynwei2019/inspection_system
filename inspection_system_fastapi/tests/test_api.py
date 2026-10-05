"""從維護建檔到提交與結果查詢的端到端 API 驗證。"""
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
_tmp = tempfile.TemporaryDirectory()
os.environ["INSPECTION_DATABASE_URL"] = f"sqlite:///{Path(_tmp.name, 'test.db').as_posix()}"
os.environ["INSPECTION_UPLOAD_DIR"] = str(Path(_tmp.name, "uploads"))

from app.main import app  # noqa: E402  設好測試資料庫再匯入
from app.db import SessionLocal  # noqa: E402
from app.seed import ensure_admin  # noqa: E402
from app.models import User  # noqa: E402
from sqlalchemy import select  # noqa: E402


class InspectionAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        command.upgrade(config, "head")
        with SessionLocal() as session:
            ensure_admin(session)
            admin = session.scalar(select(User).where(User.username == "admin"))
            admin.must_change_password = False
            session.commit()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        _tmp.cleanup()

    def setUp(self):
        self.client.cookies.clear()
        response = self.client.post("/api/v1/auth/login", json={
            "username": "admin", "password": "Admin@12345",
        })
        self.assertEqual(response.status_code, 200, response.text)

    def test_authentication_guard_and_logout(self):
        api = self.client
        self.assertEqual(api.get("/api/v1/auth/me").json()["user"]["role"], "system_admin")
        self.assertEqual(api.post("/api/v1/auth/change-password", json={
            "current_password": "wrong-password", "new_password": "Another@12345",
        }).status_code, 422)
        self.assertEqual(api.post("/api/v1/auth/logout").status_code, 204)
        self.assertEqual(api.get("/api/v1/bootstrap").status_code, 401)
        self.assertEqual(api.get("/", follow_redirects=False).status_code, 303)
        self.assertEqual(api.get("/login").status_code, 200)

    def test_abnormal_case_tracking_workflow(self):
        api = self.client
        accounts = [
            ("case_manager", "案件複查主管", "inspection_manager", "CaseManager@12345", "CaseManager@67890"),
            ("case_worker", "案件改善人員", "inspector", "CaseWorker@12345", "CaseWorker@67890"),
            ("case_outsider", "無關巡檢員", "inspector", "CaseOutside@12345", "CaseOutside@67890"),
            ("case_viewer", "案件查詢人員", "viewer", "CaseViewer@12345", "CaseViewer@67890"),
        ]
        users, clients = {}, {}
        for username, display_name, role, temporary, password in accounts:
            created = api.post("/api/v1/users", json={
                "username": username, "display_name": display_name, "role": role,
                "temporary_password": temporary, "is_active": True,
            })
            self.assertEqual(created.status_code, 201, created.text)
            users[username] = created.json()
            client = TestClient(app)
            self.assertEqual(client.post("/api/v1/auth/login", json={
                "username": username, "password": temporary,
            }).status_code, 200)
            self.assertEqual(client.post("/api/v1/auth/change-password", json={
                "current_password": temporary, "new_password": password,
            }).status_code, 200)
            clients[username] = client

        place = api.post("/api/v1/locations", json={"code": "L-CASE", "name": "異常測試區"}).json()
        item = api.post("/api/v1/items", json={"code": "C-CASE", "name": "設備溫度"}).json()
        api.put(f"/api/v1/locations/{place['id']}/items", json={"items": [
            {"item_id": item["id"], "sort_order": 1, "is_required": True},
        ]})
        draft = api.post("/api/v1/inspections", json={"location_id": place["id"]}).json()
        saved = api.patch(f"/api/v1/inspections/{draft['id']}/draft", json={
            "version": 1, "inspector": "系統管理員", "results": [
                {"item_id": item["id"], "result": "abnormal", "note": "溫度高於標準"},
            ],
        }).json()
        self.assertEqual(api.post(f"/api/v1/inspections/{draft['id']}/submit", json={
            "version": saved["version"],
        }).status_code, 200)

        cases = api.get("/api/v1/abnormal-cases").json()
        self.assertEqual(cases["total"], 1)
        record = cases["items"][0]
        self.assertEqual(record["status"], "pending")
        self.assertEqual(record["description"], "溫度高於標準")
        self.assertEqual(api.get("/api/v1/abnormal-cases/summary").json()["pending"], 1)

        inspection_detail = api.get(f"/api/v1/inspections/{draft['id']}")
        self.assertEqual(inspection_detail.status_code, 200, inspection_detail.text)
        linked_result = inspection_detail.json()["results"][0]
        self.assertEqual(linked_result["abnormal_case"]["id"], record["id"])
        self.assertEqual(linked_result["abnormal_case"]["case_number"], record["case_number"])
        self.assertEqual(linked_result["abnormal_case"]["status"], "pending")

        case_detail = api.get(f"/api/v1/abnormal-cases/{record['id']}")
        self.assertEqual(case_detail.status_code, 200, case_detail.text)
        self.assertEqual(case_detail.json()["inspection_id"], draft["id"])
        self.assertEqual(case_detail.json()["inspection_result_id"], linked_result["id"])

        assigned = api.patch(f"/api/v1/abnormal-cases/{record['id']}/assignment", json={
            "version": record["version"], "assignee_user_id": users["case_worker"]["id"],
            "due_date": "2099-12-31", "severity": "major",
        })
        self.assertEqual(assigned.status_code, 200, assigned.text)
        record = assigned.json()
        worker = clients["case_worker"]
        outsider = clients["case_outsider"]
        viewer = clients["case_viewer"]
        manager = clients["case_manager"]
        self.assertEqual(outsider.get(f"/api/v1/abnormal-cases/{record['id']}").status_code, 403)
        self.assertEqual(viewer.get(f"/api/v1/abnormal-cases/{record['id']}").status_code, 200)
        self.assertEqual(viewer.post(f"/api/v1/abnormal-cases/{record['id']}/start", json={
            "version": record["version"], "note": "",
        }).status_code, 403)

        started = worker.post(f"/api/v1/abnormal-cases/{record['id']}/start", json={
            "version": record["version"], "note": "開始降溫處理",
        })
        self.assertEqual(started.status_code, 200, started.text)
        record = started.json()
        no_photo = worker.post(f"/api/v1/abnormal-cases/{record['id']}/submit-review", json={
            "version": record["version"], "corrective_action": "清潔散熱器並降低負載",
        })
        self.assertEqual(no_photo.status_code, 422)
        uploaded = worker.post(
            f"/api/v1/abnormal-cases/{record['id']}/attachments?stage=correction",
            files={"photo": ("改善.jpg", b"\xff\xd8\xffcorrected", "image/jpeg")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        self.assertEqual(worker.get(uploaded.json()["content_url"]).status_code, 200)
        submitted = worker.post(f"/api/v1/abnormal-cases/{record['id']}/submit-review", json={
            "version": record["version"], "corrective_action": "清潔散熱器並降低負載",
        })
        self.assertEqual(submitted.status_code, 200, submitted.text)
        record = submitted.json()
        review_photo = manager.post(
            f"/api/v1/abnormal-cases/{record['id']}/attachments?stage=review",
            files={"photo": ("複查.png", b"\x89PNG\r\n\x1a\nreviewed", "image/png")},
        )
        self.assertEqual(review_photo.status_code, 201, review_photo.text)
        self.assertEqual(api.post(f"/api/v1/abnormal-cases/{record['id']}/approve", json={
            "version": record["version"], "note": "提報人不得自行結案",
        }).status_code, 422)
        closed = manager.post(f"/api/v1/abnormal-cases/{record['id']}/approve", json={
            "version": record["version"], "note": "溫度已恢復正常",
        })
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual(closed.json()["status"], "closed")
        self.assertGreaterEqual(len(closed.json()["history"]), 6)
        refreshed_link = api.get(f"/api/v1/inspections/{draft['id']}").json()["results"][0]
        self.assertEqual(refreshed_link["abnormal_case"]["status"], "closed")
        self.assertEqual(manager.delete(
            f"/api/v1/abnormal-cases/attachments/{review_photo.json()['id']}"
        ).status_code, 409)
        self.assertEqual(manager.post(
            f"/api/v1/abnormal-cases/{record['id']}/attachments?stage=review",
            files={"photo": ("late.jpg", b"\xff\xd8\xfflate", "image/jpeg")},
        ).status_code, 409)
        for client in clients.values():
            client.close()

    def test_inspection_schedule_task_workflow(self):
        api = self.client
        admin = api.get("/api/v1/auth/me").json()["user"]
        place = api.post("/api/v1/locations", json={
            "code": "L-SCHEDULE", "name": "排程測試區",
        }).json()
        item = api.post("/api/v1/items", json={
            "code": "C-SCHEDULE", "name": "每日設備確認",
        }).json()
        api.put(f"/api/v1/locations/{place['id']}/items", json={"items": [
            {"item_id": item["id"], "sort_order": 1, "is_required": True},
        ]})
        today = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
        created = api.post("/api/v1/inspection-schedules", json={
            "name": "每日設備巡檢", "location_id": place["id"],
            "assignee_user_id": admin["id"], "frequency": "daily",
            "weekdays": [], "day_of_month": None, "start_time": "00:00",
            "due_time": "23:59", "effective_from": today, "effective_to": today,
            "is_active": True,
        })
        self.assertEqual(created.status_code, 201, created.text)
        schedule = created.json()
        self.assertEqual(schedule["task_counts"]["pending"], 1)

        first = api.get("/api/v1/inspection-tasks", params={
            "date_from": today, "date_to": today, "page_size": 100,
        })
        second = api.get("/api/v1/inspection-tasks", params={
            "date_from": today, "date_to": today, "page_size": 100,
        })
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["total"], 1)
        self.assertEqual(second.json()["total"], 1)  # 同步執行不應重複產生任務
        task = first.json()["items"][0]
        self.assertTrue(task["can_start"])

        started = api.post(f"/api/v1/inspection-tasks/{task['id']}/start")
        self.assertEqual(started.status_code, 200, started.text)
        draft = started.json()["inspection"]
        self.assertEqual(started.json()["task"]["status"], "in_progress")
        self.assertEqual(api.post(f"/api/v1/inspection-tasks/{task['id']}/start").status_code, 200)
        saved = api.patch(f"/api/v1/inspections/{draft['id']}/draft", json={
            "version": draft["version"], "inspector": admin["display_name"],
            "results": [{"item_id": item["id"], "result": "normal", "note": ""}],
        }).json()
        submitted = api.post(f"/api/v1/inspections/{draft['id']}/submit", json={
            "version": saved["version"],
        })
        self.assertEqual(submitted.status_code, 200, submitted.text)
        completed = api.get("/api/v1/inspection-tasks", params={
            "date_from": today, "date_to": today, "status": "completed",
        }).json()
        self.assertEqual(completed["total"], 1)
        self.assertEqual(completed["items"][0]["inspection_id"], draft["id"])

    def test_full_workflow(self):
        api = self.client
        self.assertEqual(api.get("/health").json()["status"], "ok")
        self.assertIn("<!doctype html>", api.get("/").text.lower())
        location = api.post("/api/v1/locations", json={"code": "L-WORK", "name": "一廠倉庫"})
        self.assertEqual(location.status_code, 201, location.text)
        location = location.json()
        self.assertEqual(api.post("/api/v1/locations", json={"code": "l-work", "name": "重複"}).status_code, 409)
        first = api.post("/api/v1/items", json={"code": "C-1", "name": "消防通道", "result_type": "normal_abnormal"}).json()
        second = api.post("/api/v1/items", json={"code": "C-2", "name": "地面整潔"}).json()
        links = {"items": [{"item_id": first["id"], "sort_order": 1, "is_required": True},
                           {"item_id": second["id"], "sort_order": 2, "is_required": False}]}
        self.assertEqual(api.put(f"/api/v1/locations/{location['id']}/items", json=links).status_code, 200)
        self.assertEqual(len(api.get("/api/v1/bootstrap").json()["links"][location["id"]]), 2)
        created = api.post("/api/v1/inspections", json={"location_id": location["id"]})
        self.assertEqual(created.status_code, 201, created.text)
        draft = created.json()
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["version"], 1)
        self.assertEqual(draft["inspector"], "系統管理員")
        self.assertEqual(draft["results"][0]["name"], "消防通道")
        self.assertEqual(draft["results"][0]["attachments"], [])

        # 照片綁定單一巡檢項目；實際內容由受保護的 API 提供。
        fake_png = b"\x89PNG\r\n\x1a\n" + b"photo-test-content"
        uploaded = api.post(
            f"/api/v1/inspections/{draft['id']}/results/{first['id']}/attachments",
            files={"photo": ("現場.png", fake_png, "image/png")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        photo = uploaded.json()
        self.assertEqual(photo["mime_type"], "image/png")
        self.assertEqual(api.get(photo["content_url"]).content, fake_png)
        self.assertEqual(len(api.get(f"/api/v1/inspections/{draft['id']}").json()["results"][0]["attachments"]), 1)
        disposable = api.post(
            f"/api/v1/inspections/{draft['id']}/results/{first['id']}/attachments",
            files={"photo": ("刪除測試.webp", b"RIFF\x08\x00\x00\x00WEBPtest", "image/webp")},
        ).json()
        self.assertEqual(api.delete(f"/api/v1/attachments/{disposable['id']}").status_code, 204)
        self.assertEqual(api.get(disposable["content_url"]).status_code, 404)
        invalid = api.post(
            f"/api/v1/inspections/{draft['id']}/results/{first['id']}/attachments",
            files={"photo": ("fake.jpg", b"not-an-image", "image/jpeg")},
        )
        self.assertEqual(invalid.status_code, 415)

        # 修改維護資料後，既有草稿仍保留開始時的項目快照。
        api.patch(f"/api/v1/items/{first['id']}", json={"name": "新的檢查名稱", "is_active": False})
        api.patch(f"/api/v1/locations/{location['id']}", json={"name": "新的地點名稱"})
        saved = api.get(f"/api/v1/inspections/{draft['id']}").json()
        self.assertEqual(saved["location_name"], "一廠倉庫")
        self.assertEqual(saved["results"][0]["name"], "消防通道")
        self.assertEqual(api.post(f"/api/v1/inspections/{draft['id']}/submit", json={"version": 1}).status_code, 422)
        self.assertEqual(api.patch(f"/api/v1/inspections/{draft['id']}/draft", json={
            "version": 1, "inspector": "Jimmy", "results": [
                {"item_id": first["id"], "result": "na", "note": ""},
                {"item_id": second["id"], "result": None, "note": ""}],
        }).status_code, 422)

        payload = {"version": 1, "inspector": "Jimmy", "results": [
            {"item_id": first["id"], "result": "abnormal", "note": ""},
            {"item_id": second["id"], "result": None, "note": ""}]}
        updated = api.patch(f"/api/v1/inspections/{draft['id']}/draft", json=payload)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["version"], 2)
        self.assertEqual(api.patch(f"/api/v1/inspections/{draft['id']}/draft", json=payload).status_code, 409)
        self.assertEqual(api.post(f"/api/v1/inspections/{draft['id']}/submit", json={"version": 2}).status_code, 422)
        payload["version"] = 2
        payload["results"][0]["note"] = "通道堆有紙箱"
        self.assertEqual(api.patch(f"/api/v1/inspections/{draft['id']}/draft", json=payload).status_code, 200)
        submitted = api.post(f"/api/v1/inspections/{draft['id']}/submit", json={"version": 3})
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["status"], "submitted")
        self.assertEqual(submitted.json()["abnormal_count"], 1)
        self.assertEqual(len(submitted.json()["results"][0]["attachments"]), 1)
        self.assertTrue(submitted.json()["number"].startswith("INSP-"))
        self.assertEqual(api.post(f"/api/v1/inspections/{draft['id']}/submit", json={"version": 4}).status_code, 409)
        self.assertEqual(api.delete(f"/api/v1/attachments/{photo['id']}").status_code, 409)

        params = {"status": "submitted", "location_id": location["id"], "has_abnormal": True, "page": 1, "page_size": 10}
        result = api.get("/api/v1/inspections", params=params)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["total"], 1)
        self.assertEqual(result.json()["abnormal_count"], 1)
        self.assertEqual(result.json()["items"][0]["results"][1]["result"], None)
        self.assertGreaterEqual(api.get("/api/v1/dashboard").json()["submitted_count"], 1)
        params["has_abnormal"] = False
        self.assertEqual(api.get("/api/v1/inspections", params=params).json()["total"], 0)
        today = datetime.now().date().isoformat()
        self.assertEqual(api.get("/api/v1/inspections", params={"date_from": today, "date_to": today}).status_code, 200)

    def test_validation_and_foreign_keys(self):
        api = self.client
        place = api.post("/api/v1/locations", json={"code": "L-VALID", "name": "驗證位置"}).json()
        self.assertEqual(api.post("/api/v1/inspections", json={"location_id": place["id"]}).status_code, 422)
        self.assertEqual(api.put(f"/api/v1/locations/{place['id']}/items", json={"items": [
            {"item_id": "missing", "sort_order": 1}]}).status_code, 422)
        item = api.post("/api/v1/items", json={"code": "C-VALID", "name": "需檢查"}).json()
        self.assertEqual(api.put(f"/api/v1/locations/{place['id']}/items", json={"items": [
            {"item_id": item["id"], "sort_order": 2}]}).status_code, 422)
        api.put(f"/api/v1/locations/{place['id']}/items", json={"items": [
            {"item_id": item["id"], "sort_order": 1}]})
        api.patch(f"/api/v1/locations/{place['id']}", json={"is_active": False})
        self.assertEqual(api.post("/api/v1/inspections", json={"location_id": place["id"]}).status_code, 422)

    def test_role_permissions_and_user_management(self):
        api = self.client
        accounts = [
            ("manager1", "巡檢主管", "inspection_manager", "Manager@12345", "Manager@67890"),
            ("inspector1", "第一巡檢員", "inspector", "Inspector@12345", "Inspector@67890"),
            ("viewer1", "查詢同仁", "viewer", "Viewer@12345", "Viewer@67890"),
        ]
        created = {}
        for username, name, role, temporary, _new in accounts:
            response = api.post("/api/v1/users", json={
                "username": username, "display_name": name, "department": "品保部",
                "email": "", "role": role, "temporary_password": temporary, "is_active": True,
            })
            self.assertEqual(response.status_code, 201, response.text)
            self.assertTrue(response.json()["must_change_password"])
            created[role] = response.json()
        self.assertGreaterEqual(len(api.get("/api/v1/audit-logs").json()["items"]), 3)
        self.assertEqual(api.patch(f"/api/v1/users/{api.get('/api/v1/auth/me').json()['user']['id']}",
                                   json={"role": "viewer"}).status_code, 422)

        clients = {}
        for username, _name, role, temporary, new_password in accounts:
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={"username": username, "password": temporary})
            self.assertEqual(login.status_code, 200, login.text)
            self.assertTrue(login.json()["user"]["must_change_password"])
            self.assertEqual(client.get("/api/v1/dashboard").status_code, 403)
            changed = client.post("/api/v1/auth/change-password", json={
                "current_password": temporary, "new_password": new_password,
            })
            self.assertEqual(changed.status_code, 200, changed.text)
            clients[role] = client

        manager = clients["inspection_manager"]
        self.assertEqual(manager.get("/api/v1/inspection-schedules").status_code, 200)
        place = manager.post("/api/v1/locations", json={"code": "L-ROLE", "name": "權限測試區"})
        self.assertEqual(place.status_code, 201, place.text)
        check = manager.post("/api/v1/items", json={"code": "C-ROLE", "name": "權限測試項目"})
        self.assertEqual(check.status_code, 201, check.text)
        manager.put(f"/api/v1/locations/{place.json()['id']}/items", json={"items": [
            {"item_id": check.json()["id"], "sort_order": 1, "is_required": True},
        ]})
        self.assertEqual(manager.get("/api/v1/users").status_code, 403)

        inspector = clients["inspector"]
        self.assertEqual(inspector.get("/api/v1/inspection-schedules").status_code, 403)
        draft = inspector.post("/api/v1/inspections", json={"location_id": place.json()["id"]})
        self.assertEqual(draft.status_code, 201, draft.text)
        self.assertEqual(inspector.get("/api/v1/locations").status_code, 200)
        self.assertEqual(inspector.post("/api/v1/locations", json={"code": "NO", "name": "不允許"}).status_code, 403)

        other_draft = manager.post("/api/v1/inspections", json={"location_id": place.json()["id"]}).json()
        self.assertEqual(inspector.get(f"/api/v1/inspections/{other_draft['id']}").status_code, 403)
        protected_photo = manager.post(
            f"/api/v1/inspections/{other_draft['id']}/results/{check.json()['id']}/attachments",
            files={"photo": ("evidence.jpg", b"\xff\xd8\xffprotected-photo", "image/jpeg")},
        ).json()
        self.assertEqual(inspector.get(protected_photo["content_url"]).status_code, 403)
        own = inspector.get("/api/v1/inspections", params={"status": "draft", "page_size": 100}).json()["items"]
        self.assertTrue(own)
        self.assertTrue(all(row["inspector_user_id"] == created["inspector"]["id"] for row in own))

        viewer = clients["viewer"]
        self.assertEqual(viewer.get("/api/v1/inspection-tasks").status_code, 403)
        self.assertEqual(viewer.post("/api/v1/inspections", json={"location_id": place.json()["id"]}).status_code, 403)
        self.assertEqual(viewer.get("/api/v1/inspections").status_code, 200)
        self.assertEqual(viewer.get("/api/v1/inspections", params={"status": "draft"}).status_code, 403)
        self.assertEqual(viewer.get(f"/api/v1/inspections/{other_draft['id']}").status_code, 403)
        self.assertEqual(viewer.get(protected_photo["content_url"]).status_code, 403)
        saved_other = manager.patch(f"/api/v1/inspections/{other_draft['id']}/draft", json={
            "version": 1, "inspector": "巡檢主管", "results": [
                {"item_id": check.json()["id"], "result": "normal", "note": ""},
            ],
        }).json()
        self.assertEqual(manager.post(f"/api/v1/inspections/{other_draft['id']}/submit", json={
            "version": saved_other["version"],
        }).status_code, 200)
        self.assertEqual(viewer.get(protected_photo["content_url"]).status_code, 200)
        reset = api.post(f"/api/v1/users/{created['viewer']['id']}/reset-password", json={
            "temporary_password": "ViewerReset@12345",
        })
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(viewer.get("/api/v1/auth/me").status_code, 401)
        lock_client = TestClient(app)
        for _ in range(5):
            self.assertEqual(lock_client.post("/api/v1/auth/login", json={
                "username": "viewer1", "password": "wrong-password",
            }).status_code, 401)
        self.assertEqual(lock_client.post("/api/v1/auth/login", json={
            "username": "viewer1", "password": "ViewerReset@12345",
        }).status_code, 423)
        lock_client.close()
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    unittest.main()
