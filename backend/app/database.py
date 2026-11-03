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
    "ALTER TABLE conversion_jobs ADD COLUMN IF NOT EXISTS project_number VARCHAR(25)",
    # temp numbers are reused only for the same plant + project; older master rows have no project (NULL)
    "ALTER TABLE material_master_import ADD COLUMN IF NOT EXISTS project_number VARCHAR(25)",
    # SPIR descriptions can run to well over 1000 characters (multi-line spec text); no length limit here
    *(f"ALTER TABLE extracted_lines ALTER COLUMN {col} TYPE TEXT"
      for col in ("tag", "old_material_number", "description", "mfr_part_number", "mfr_name", "spir_number",
                  "sap_material_number", "temp_number", "uom", "country_name", "quantity")),
    # the same for every other column filled from SPIR text - a long value used to fail the whole conversion
    *(f"ALTER TABLE material_master_import ALTER COLUMN {col} TYPE TEXT"
      for col in ("old_material_number_spf_number", "material_description", "base_unit_of_measure",
                  "manufacturers_part_number", "manufacturer_name", "cdc_spir_number", "sap_material_number")),
    *(f"ALTER TABLE conversion_jobs ALTER COLUMN {col} TYPE TEXT"
      for col in ("input_filename", "output_filename", "submission_filename")),
    "ALTER TABLE material_numbers ALTER COLUMN item_key TYPE TEXT",
    # owner of each conversion / combine run: the History page shows each user only their own records
    *(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)"
      for table in ("conversion_jobs", "combine_tasks")),
    "CREATE INDEX IF NOT EXISTS ix_conversion_jobs_user_id ON conversion_jobs (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_combine_tasks_user_id ON combine_tasks (user_id)",
    # older rows only stored the display name: link them to the user with that name, only when exactly one
    # user has it (an ambiguous or unknown name stays NULL - better hidden than shown to the wrong user)
    *(f"UPDATE {table} t SET user_id = u.id FROM users u "
      f"WHERE t.user_id IS NULL AND t.user_name = COALESCE(u.full_name, u.username) "
      f"AND (SELECT count(*) FROM users x WHERE COALESCE(x.full_name, x.username) = t.user_name) = 1"
      for table in ("conversion_jobs", "combine_tasks")),
]


def upgrade_columns(conn) -> None:
    from sqlalchemy import text

    for stmt in _ADDED_COLUMNS:
        conn.execute(text(stmt))
