"""使用 SQLite backup API 建立資料庫與照片的可攜式備份。"""
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .db import DATABASE_URL, PROJECT_ROOT


def main():
    if not DATABASE_URL.startswith("sqlite:///") or ":memory:" in DATABASE_URL:
        raise SystemExit("備份指令僅支援檔案型 SQLite 資料庫")
    source = Path(DATABASE_URL.removeprefix("sqlite:///"))
    if not source.is_file():
        raise SystemExit(f"找不到資料庫：{source}")
    folder = PROJECT_ROOT / "backups"
    folder.mkdir(exist_ok=True)
    destination = folder / f"inspection-{datetime.now():%Y%m%d-%H%M%S}.zip"
    upload_dir = Path(os.getenv("INSPECTION_UPLOAD_DIR", str(PROJECT_ROOT / "data" / "uploads"))).resolve()
    with tempfile.TemporaryDirectory() as temporary:
        database_copy = Path(temporary) / "inspection.db"
        with sqlite3.connect(source) as original, sqlite3.connect(database_copy) as backup:
            original.backup(backup)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(database_copy, "data/inspection.db")
            if upload_dir.is_dir():
                for photo in upload_dir.iterdir():
                    if photo.is_file() and not photo.name.startswith("."):
                        archive.write(photo, f"data/uploads/{photo.name}")
    print(f"備份完成：{destination}")


if __name__ == "__main__":
    main()
