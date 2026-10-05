# 巡檢系統｜inspection_system

以 FastAPI 與 SQLite 建置的巡檢系統，同一個服務提供網頁及 API，包含帳號權限、地點與項目維護、巡檢排程、照片附件、結果查詢及異常改善追蹤。

## 操作手冊

請參閱 [圖文操作手冊](docs/操作手冊.md)，包含登入改密碼、維護設定、排程、照片上傳及異常結案的實際畫面。亦提供 [可列印 HTML](docs/操作手冊.html) 與 [PDF](docs/操作手冊.pdf)。

## 原始碼與目錄

請直接修改 `inspection_system_fastapi/` 中的原始碼，使用 Git 追蹤變更。根目錄的 `inspection_system_fastapi_schedule_mvp.zip` 保留作為最初匯入來源；日常開發不必解壓或重新封裝它。

```text
inspection_system_fastapi/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── models.py            # SQLAlchemy 資料模型
│   ├── routers/             # 登入、維護、巡檢、排程及異常 API
│   ├── static/              # HTML 與 JavaScript
│   ├── bootstrap_admin.py   # 首次管理員初始化
│   └── backup.py            # SQLite 與照片備份
├── migrations/             # Alembic 資料庫遷移
├── tests/test_api.py        # 端到端 API 測試
├── requirements.txt        # 執行依賴
├── requirements-dev.txt    # 測試依賴
└── start_server.bat         # Windows 一鍵啟動
```

詳細資料儲存與角色說明見 [應用程式 README](inspection_system_fastapi/README.md)。

## 安裝與啟動

建議使用 Python 3.12，已在 Linux 的 Python 3.12.14 驗證。系統使用 SQLite，不需要另外啟動資料庫服務，也沒有獨立的前端建置步驟。安裝依賴需要存取 Python 套件來源。

以下指令從儲存庫根目錄開始；進入應用程式目錄後，遷移、測試與啟動指令都在該目錄執行。

### Linux／macOS

```bash
cd inspection_system_fastapi
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip check
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.bootstrap_admin
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Windows PowerShell

```powershell
cd inspection_system_fastapi
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.bootstrap_admin
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Windows 也可雙擊 `inspection_system_fastapi/start_server.bat`。它會初始化依賴與資料庫，並以 `0.0.0.0:8000` 啟動，供同網路裝置連線；不會自動匯入示範資料。

本機啟動後，在瀏覽器輸入 `http://127.0.0.1:8000/`；API 文件路徑為 `/docs`，健康檢查 `/health` 應回傳 `{"status":"ok"}`。按 `Ctrl+C` 停止服務。雲端環境的 loopback 地址僅供該機器內部驗證，不能當作外部預覽網址。

後續啟動可重用 `.venv`；更新程式後先安裝依賴並執行 `alembic upgrade head`。`app.bootstrap_admin` 可重複執行，已有使用者時不會覆蓋帳號或密碼。

## 首次登入

預設帳號為 `admin`，初始密碼為 `Admin@12345`。第一次登入必須先修改密碼，才能使用其他功能；新密碼至少 10 個字元，且不可與舊密碼相同。

若要自訂初始帳號，請在第一次初始化前設定 `INSPECTION_ADMIN_USERNAME`、`INSPECTION_ADMIN_PASSWORD` 及 `INSPECTION_ADMIN_DISPLAY_NAME`。透過安全的環境設定提供密碼，勿提交至 Git。修改這些變數不會重設已存在的帳號；已有帳號請使用帳號管理功能。

系統管理員可建立巡檢管理員、巡檢人員及查詢人員。新帳號與重設密碼後的帳號也必須先修改臨時密碼。連續登入失敗 5 次會鎖定 15 分鐘。

## 完整試用流程

建議使用獨立的測試資料庫試用。下列流程會建立帳號、地點、排程及巡檢紀錄；若在既有資料庫操作，這些資料會持續保留。

1. **登入及準備帳號**：使用管理員登入並修改初始密碼。在「帳號管理」建立巡檢人員與另一位管理員，讓各帳號完成首次改密碼；異常結案需由符合權限且非提報人的管理員操作。
2. **維護地點與項目**：建立啟用的地點，例如「一廠倉庫」，及巡檢項目，例如「消防通道」。在「地點項目設定」勾選適用項目、順序與必填規則。地點必須有啟用的關聯項目，才能用於巡檢。
3. **建立巡檢排程**：指定地點、巡檢人員、頻率、有效日期及執行時間。可先建立當日的一次性排程。任務依 `Asia/Taipei` 時區產生，請確認日期與負責人。
4. **執行巡檢與上傳照片**：由指定人員啟動任務，逐項填寫結果。選擇異常時填寫說明，並上傳 JPEG、PNG 或 WebP 照片。可先暫存草稿；每項預設最多 5 張、每張 5 MB。
5. **提交與查詢**：確認必填項目後提交，排程任務應變成已完成。結果查詢可查看紀錄與照片；提交後紀錄唯讀，不能再新增或刪除巡檢照片。
6. **追蹤異常**：異常項目提交後會自動建立案件。管理員指定負責人、期限及嚴重度；負責人開始處理、填寫改善說明並上傳改善照片，再送出複查。重大異常至少需要一張改善照片。
7. **複查與結案**：由符合權限的管理員複查，可上傳複查照片、退回改善或結案。確認案件狀態與處理歷程，並在原巡檢結果中確認案件連結。

若只需要快速展示資料，可在應用程式目錄執行 `.venv/bin/python -m app.seed`（Windows 改用 `.venv\Scripts\python.exe`）。它只在地點表為空時匯入範例，日常啟動不必執行。

## 環境變數與資料位置

| 變數 | 預設值／用途 |
| --- | --- |
| `INSPECTION_DATABASE_URL` | 應用程式目錄下的 `data/inspection.db`，使用 SQLite URL |
| `INSPECTION_UPLOAD_DIR` | 應用程式目錄下的 `data/uploads/` |
| `INSPECTION_ADMIN_USERNAME` | 首次初始化帳號，預設 `admin` |
| `INSPECTION_ADMIN_PASSWORD` | 首次初始化密碼，預設為上述開發用密碼 |
| `INSPECTION_ADMIN_DISPLAY_NAME` | 首次初始化顯示名稱，預設「系統管理員」 |
| `INSPECTION_SESSION_SECONDS` | Session 有效秒數，預設 `28800`（8 小時） |
| `INSPECTION_COOKIE_SECURE` | 預設 `false`；使用 HTTPS 時設為 `true` |
| `INSPECTION_PHOTO_MAX_BYTES` | 每張照片上限，預設 `5242880` bytes |
| `INSPECTION_PHOTO_MAX_COUNT` | 每個巡檢項目照片上限，預設 `5` |
| `ABNORMAL_PHOTO_MAX_COUNT` | 每個改善／複查階段照片上限，預設 `5` |

遷移、初始化、服務及備份需使用一致的資料庫與上傳目錄設定。資料庫、上傳照片、備份、虛擬環境及 Python 快取由 `.gitignore` 排除；Git 版本控制不會備份業務資料。

## 測試與驗證範圍

在應用程式目錄執行：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```

Windows 對應指令：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

目前包含 6 項 API 測試，涵蓋登入權限、帳號管理、維護與巡檢提交、照片附件、排程任務、異常改善及結案。測試自動建立臨時 SQLite 資料庫與上傳目錄，不使用日常資料庫；測試帳號假設使用預設初始化設定，若注入了自訂管理員帳號變數，請只在測試程序中取消這些變數。

目前已在 Python 3.12 驗證 6 項測試全部通過，並另外驗證初始管理員強制改密碼及新舊密碼登入行為。這些是 API 驗證；瀏覽器互動及真實照片的顯示效果仍需依上述流程手動確認。Starlette 的 httpx 棄用警告目前不影響測試結果。

## 備份與還原

```bash
.venv/bin/python -m app.backup
```

Windows 使用 `.\.venv\Scripts\python.exe -m app.backup`。備份輸出到 `backups/inspection-日期時間.zip`，包含 `data/inspection.db` 與照片。指令使用 SQLite backup API 複製資料庫；若需要資料庫和照片在同一時間點完全一致，請在沒有上傳或刪除操作時備份。不要只複製使用中的資料庫檔案。

還原時先停止服務並保留目前資料，再將備份解壓到獨立目錄，檢查資料庫與照片內容。將資料庫及照片放到設定的路徑，使用相同環境設定執行遷移、啟動服務，確認登入、歷史紀錄與附件可讀後再使用。系統尚未提供自動還原指令。

## 常見問題

| 現象 | 處理方式 |
| --- | --- |
| 找不到 `app` 或 Alembic 設定 | 切換至 `inspection_system_fastapi/` 再執行指令 |
| `no such table` | 確認資料庫設定一致，執行 `alembic upgrade head` |
| 8000 連接埠已占用 | 確認是否已有服務；或以 `--port 8001` 啟動並使用相同連接埠存取 |
| 登入後功能回傳 403 | 先修改初始／臨時密碼，再確認角色權限 |
| 草稿更新回傳 409 | 重新載入最新草稿後再操作，避免覆蓋其他頁面已儲存的內容 |
| 找不到可巡檢地點 | 確認地點、項目均啟用，且已建立地點與項目的關聯 |
| HTTP 開發環境無法維持登入 | 檢查是否誤設 `INSPECTION_COOKIE_SECURE=true` |

## 部署範圍

此專案尚未內建 HTTPS 與通知。正式對外使用前需配置 HTTPS 反向代理，並設定安全 Cookie、管理員密碼及資料備份；不要直接將 HTTP 8000 連接埠公開。舊展示版瀏覽器 `localStorage` 資料不會自動匯入 SQLite。

雲端環境快照保留檔案與依賴，執行中的服務需在新工作階段重新啟動。先前 onboarding 使用 `/workspace/inspection-dev/inspection_system_fastapi` 的解壓副本；本儲存庫的開發流程以 `inspection_system_fastapi/` 為準，切勿混用兩份程式及資料庫。若環境啟動指引仍指向舊副本，請同步更新為本儲存庫目錄。
