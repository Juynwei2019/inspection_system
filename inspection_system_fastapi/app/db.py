"""SQLite 連線、路徑及 request 範圍的 Session。"""
import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "inspection.db"
DATABASE_URL = os.getenv("INSPECTION_DATABASE_URL", f"sqlite:///{DEFAULT_DB.as_posix()}")

if DATABASE_URL.startswith("sqlite:///") and ":memory:" not in DATABASE_URL:
    db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 10} if DATABASE_URL.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def configure_sqlite(connection, _):
    if engine.dialect.name == "sqlite":
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    with SessionLocal() as session:
        yield session
