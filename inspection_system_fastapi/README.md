# 巡檢系統｜FastAPI × SQLite

已整合登入、主頁、維護模組、巡檢排程、巡檢模組、照片附件、結果查詢、異常追蹤，以及帳號與角色權限。網頁與 API 由同一個 FastAPI 服務提供，資料集中儲存在 SQLite；未登入或權限不足時無法存取對應功能。

完整安裝、操作流程、環境變數與疑難排解請見 [儲存庫 README](../README.md)。以下補充應用程式的角色與資料行為。

## Windows 一鍵啟動

進入 Git 儲存庫中的 `inspection_system_fastapi` 目錄（或解壓原始 ZIP）後，雙擊專案目錄內的 `start_server.bat`。首次執行會從已安裝的 Python **3.12、3.13、3.14** 中選一個建立 `.venv`、安裝套件、更新 SQLite 資料表、建立初始管理員並啟動服務；不會自動加入展示用巡檢資料。開啟 **http://127.0.0.1:8000/**；同網路的其他電腦可使用 `http://伺服器IP:8000/`。在視窗中按 `Ctrl+C` 可停止伺服器。

首次登入帳號：

```text
帳號：admin
密碼：Admin@12345
```

首次登入會強制修改初始密碼。若要在第一次啟動前自訂帳密，可設定 `INSPECTION_ADMIN_USERNAME`、`INSPECTION_ADMIN_PASSWORD`、`INSPECTION_ADMIN_DISPLAY_NAME` 環境變數。

## 帳號與角色

系統管理員可在左側「帳號管理」建立帳號、分配角色、停用帳號、重設臨時密碼及登出指定帳號的所有裝置。

| 角色 | 權限 |
| --- | --- |
| 系統管理員 | 全部功能、帳號管理與操作紀錄 |
| 巡檢管理員 | 地點／項目維護、執行巡檢、查看全部結果 |
| 巡檢人員 | 執行巡檢，只能查看及繼續自己的紀錄 |
| 查詢人員 | 唯讀查看已提交的全部巡檢結果 |

新帳號第一次登入或由管理員重設密碼後，必須先修改臨時密碼。連續登入失敗 5 次會鎖定 15 分鐘；停用帳號、修改角色或重設密碼時，既有登入狀態會立即失效。系統不允許停用自己，也不允許移除最後一位有效的系統管理員。

從舊版升級時，既有 `admin` 會自動轉為系統管理員，巡檢及維護資料會保留。因登入機制已改為伺服器 Session，升級後瀏覽器需要重新登入一次。

## 安裝與啟動（Windows PowerShell）

在 `inspection_system_fastapi` 目錄執行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.bootstrap_admin
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

在瀏覽器開啟 **http://127.0.0.1:8000/**。`app.seed` 是選用的示範資料匯入，只會在地點表為空時建立與原先 HTML 類似的範例；正式資料可略過這一步。先前遇過 Python 3.14 的 `pydantic-core` 建置問題，以上指令採 Python 3.12 虛擬環境。

macOS／Linux 對應指令：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.bootstrap_admin
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API 文件在 **http://127.0.0.1:8000/docs**，健康檢查在 **http://127.0.0.1:8000/health**。

## 資料位置與工作方式

- 預設資料庫：`data/inspection.db`，重啟服務後資料仍在。可設定環境變數 `INSPECTION_DATABASE_URL` 指向其他 SQLite 檔案；記得遷移與服務啟動都要使用相同設定。
- 密碼以 PBKDF2-SHA256 加鹽雜湊保存；瀏覽器只保存隨機 HttpOnly、SameSite Cookie，伺服器資料庫保存雜湊後的 Session，預設有效 8 小時。
- 若已經透過 HTTPS 提供服務，請設定 `INSPECTION_COOKIE_SECURE=true`，讓登入 Cookie 僅透過 HTTPS 傳送。
- `app.bootstrap_admin` 只會在沒有任何使用者時建立初始管理員，不會覆蓋已修改的密碼。若需要展示資料，可另外執行 `python -m app.seed`。
- 巡檢開始時，伺服器將當下地點與項目複製為該次巡檢的快照。維護資料後續異動不會改寫舊紀錄。
- 草稿在後端儲存；更新包含 `version`，其他頁面已更新草稿時會回傳 409，避免靜默覆蓋。
- 提交後紀錄唯讀；必填項目與異常說明由後端再次驗證。
- 每個巡檢項目可上傳最多 5 張 JPEG、PNG 或 WebP 照片，單張預設上限 5 MB。照片存放於 `data/uploads/`，資料庫只保存檔案資訊；提交後不可新增或刪除。可用 `INSPECTION_UPLOAD_DIR`、`INSPECTION_PHOTO_MAX_BYTES`、`INSPECTION_PHOTO_MAX_COUNT` 調整儲存位置與限制。
- 巡檢提交後，每個異常項目會自動建立異常案件；既有已提交異常也會在升級時補建案件。
- 巡檢排程支援單次、每日、每週及每月規則，並依 `Asia/Taipei` 時區同步最近 31 天至未來 30 天的任務。
- 排程任務可顯示待執行、執行中、已完成、已逾期及已取消；由指定人員啟動後會建立巡檢草稿，提交時自動完成任務。
- 修改或停用排程時，尚未開始的未來任務會重新同步；已開始及已完成的任務不會被改寫。
- 異常案件支援負責人、期限、嚴重度、改善說明、改善／複查照片、退回與結案歷程。重大異常送複查前至少需要一張改善照片。
- 改善及複查階段預設各最多 5 張照片，可用 `ABNORMAL_PHOTO_MAX_COUNT` 調整。
- 原展示版 HTML 的瀏覽器 `localStorage` **不會自動搬入**新資料庫。若其中有需要保存的真實資料，應先另做明確匯入流程。

## 備份與測試

在服務運作時可執行一致性備份：

```powershell
.\.venv\Scripts\python.exe -m app.backup
```

備份輸出為 `backups/inspection-日期時間.zip`，其中同時包含一致性的 SQLite 資料庫與照片目錄。不要只複製使用中的 `.db` 檔作為備份；請定期測試將壓縮檔還原後能否讀取。

安裝測試依賴並執行端到端 API 測試：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 使用範圍

這一版已有登入、固定四角色、使用者管理、Session 撤銷、巡檢排程、巡檢照片、異常改善追蹤及操作紀錄。通知與 HTTPS 尚未加入。備份時請同時保存 SQLite 資料庫及 `data/uploads/` 照片目錄；若要跨網際網路正式使用，請先部署 HTTPS 反向代理，不要直接將 HTTP 8000 連接埠暴露至公開網路。
