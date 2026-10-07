from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# create_all() only creates missing tables; columns added to an existing table are listed here and
# added at start-up (idempotent). Older conversions simply have NULL in them.
_ADDED_COLUMNS = [
    "ALTER TABLE conversion_jobs ADD COLUMN IF NOT EXISTS submission_filename VARCHAR(255)",
    "ALTER TABLE conversion_jobs ADD COLUMN IF NOT EXISTS submission_file BYTEA",
]


def upgrade_columns(conn) -> None:
    from sqlalchemy import text

    for stmt in _ADDED_COLUMNS:
        conn.execute(text(stmt))
