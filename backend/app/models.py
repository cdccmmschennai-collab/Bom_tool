"""PostgreSQL tables.

plants            - dropdown values (plant type DUKHAN / OTHER + planning plant code)
country_codes     - HERLD / T005 reference (seeded from COUNTRY_REFERENCE.xlsx)
number_sequences  - last Material Temp Number used, per numbering scope and kind
material_numbers  - remembers which temp number a material / equipment already got,
                    so the same item keeps its number across uploads
conversion_jobs   - history of every conversion, including input and output files
users             - accounts that can sign in (created with `python -m app.manage create-user`)
auth_sessions     - signed-in sessions; only a hash of the cookie token is stored
extracted_lines   - every BOM line a conversion produced (searched on the Parts Master page)
combine_tasks     - "Combine" runs from the History page: progress and the combined file (kept 24 hours)
material_master_import - the material master list (one row per issued temp number). Existing numbers are
                    reused and continued from it, and every conversion adds its new lines to it.
"""
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, Numeric,
                        String, Table, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Plant(Base):
    __tablename__ = "plants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_type: Mapped[str] = mapped_column(String(10), index=True)  # DUKHAN | OTHER
    code: Mapped[str] = mapped_column(String(4), unique=True)        # IWERK, max 4 chars
    name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class CountryCode(Base):
    __tablename__ = "country_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    name_upper: Mapped[str] = mapped_column(String(100), index=True)
    code: Mapped[str] = mapped_column(String(3))


class NumberSequence(Base):
    __tablename__ = "number_sequences"
    __table_args__ = (UniqueConstraint("scope", "kind", name="uq_sequence_scope_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(30))   # e.g. "DUKHAN:D100" or "OTHER"
    kind: Mapped[str] = mapped_column(String(10))    # EQUIPMENT | SPARE
    last_value: Mapped[int] = mapped_column(BigInteger)


class MaterialNumber(Base):
    __tablename__ = "material_numbers"
    __table_args__ = (UniqueConstraint("scope", "kind", "item_key", name="uq_material_scope_kind_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(10))
    item_key: Mapped[str] = mapped_column(String(300))  # tag no for equipment, SAP/SPF no for spares
    temp_number: Mapped[int] = mapped_column(BigInteger)
    first_job_id: Mapped[int | None] = mapped_column(ForeignKey("conversion_jobs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversionJob(Base):
    __tablename__ = "conversion_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    plant_type: Mapped[str] = mapped_column(String(10))
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True)
    plant_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(10))  # SUCCESS | FAILED
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    input_filename: Mapped[str] = mapped_column(String(255))
    output_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submission_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    spir_numbers: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    equipment_count: Mapped[int] = mapped_column(Integer, default=0)
    spare_count: Mapped[int] = mapped_column(Integer, default=0)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    input_file: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    output_file: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    submission_file: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)

    plant: Mapped[Plant | None] = relationship()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)      # stored lower-case
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)  # lower-case
    full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def display_name(self) -> str:
        return self.full_name or self.username


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 of the cookie token
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship()




class ExtractedLine(Base):
    """One BOM line of a conversion, kept searchable for the Parts Master page.
    Deleting the conversion deletes its lines (ON DELETE CASCADE)."""
    __tablename__ = "extracted_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("conversion_jobs.id", ondelete="CASCADE"), index=True)
    serial: Mapped[int] = mapped_column(Integer)
    category: Mapped[str | None] = mapped_column(String(20), nullable=True)          # B = equipment, L = spare
    tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sap_material_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    old_material_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    planning_plant: Mapped[str | None] = mapped_column(String(50), nullable=True)
    uom: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mfr_part_number: Mapped[str | None] = mapped_column(String(255), nullable=True)  # full value
    mfr_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    spir_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[str | None] = mapped_column(String(50), nullable=True)

class CombineTask(Base):
    """One "Combine" request from the History page. Progress lives in the database (not in memory)
    so any backend worker can answer the progress polls."""
    __tablename__ = "combine_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    kind: Mapped[str] = mapped_column(String(10))       # WORKING | SUBMISSION
    job_ids: Mapped[list] = mapped_column(JSONB)
    user_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(10))     # RUNNING | DONE | FAILED
    done: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)

# Created and filled outside the app (pgAdmin import); create_all() only creates it when it is missing.
material_master_import = Table(
    "material_master_import", Base.metadata,
    Column("material_temp_number", BigInteger),
    Column("material_type_category", String(20)),             # B = equipment, L = spare
    Column("material_is_equipment_indicator", Boolean),
    Column("old_material_number_spf_number", String(255)),
    Column("material_description", String(500)),
    Column("maintenance_planning_plant", String(50)),
    Column("base_unit_of_measure", String(50)),
    Column("manufacturers_part_number", String(255)),
    Column("manufacturer_name", String(255)),
    Column("mm_requirement_material_type", String(50)),
    Column("mm_requirement_material_group", String(50)),
    Column("cdc_spir_number", String(255)),
    Column("reorder_point_minimum_qty", Numeric),
    Column("maximum_stock_level_max_qty", Numeric),
    Column("sap_material_number", String(100)),
)
