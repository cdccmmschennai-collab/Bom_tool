"""Material Temp Number allocation stored in PostgreSQL.

* A new temp number is never one that was already issued, in any plant: there is one running sequence per
  kind (equipment / spare) for all plants, and it always continues after the highest number already in the
  material master (material_master_import) - gaps and duplicate values there are ignored.
* Reuse is per numbering scope (plant based - see Settings.numbering_scope): the same equipment tag gets
  the same number again, and a spare whose manufacturer part number is already in the master for the
  scope's plants gets the master's temp number again (one part number = one temp number).
* The sequence row is locked (SELECT ... FOR UPDATE) for the whole conversion, so two users
  converting at the same time can never receive the same number.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import MaterialNumber, NumberSequence, Plant, material_master_import as master

EQUIPMENT = "EQUIPMENT"
SPARE = "SPARE"
SEQUENCE_SCOPE = "ALL"  # new numbers come from one sequence per kind, shared by every plant


def numbering_scope(plant_type: str, plant_code: str | None) -> str:
    if get_settings().numbering_scope == "plant" and plant_code:
        return f"{plant_type}:{plant_code}"
    return plant_type


def scope_plant_codes(db: Session, plant_type: str, plant_code: str | None) -> list[str]:
    """Planning plants whose material master rows share the numbering scope."""
    if get_settings().numbering_scope == "plant" and plant_code:
        return [plant_code]
    return list(db.scalars(select(Plant.code).where(Plant.plant_type == plant_type)))


class DbAllocator:
    def __init__(self, db: Session, scope: str, plant_codes: list[str] | None = None):
        s = get_settings()
        self.db = db
        self.scope = scope
        self.plant_codes = plant_codes or []
        self.start = {EQUIPMENT: s.equipment_start, SPARE: s.spare_start}
        self._cache: dict[tuple[str, str], int] = {}
        self._seq: dict[str, NumberSequence] = {}
        self.new_numbers = 0
        self.job_id: int | None = None

    def _master_rows(self, kind: str):
        is_eq = master.c.material_is_equipment_indicator
        return (master.c.maintenance_planning_plant.in_(self.plant_codes),
                is_eq.is_(True) if kind == EQUIPMENT else is_eq.is_not(True))

    def _master_max(self, kind: str) -> int | None:
        """Highest temp number in the whole master (all plants) within the kind's range, e.g. 40001-99999
        for equipment and 500001-999999 for spares. SAP numbers (8 digits) in the column are outside both."""
        start = self.start[kind]
        temp = master.c.material_temp_number
        return self.db.execute(
            select(func.max(temp)).where(temp >= start, temp < 10 ** len(str(start)))
        ).scalar()

    def _master_number(self, kind: str, key: str) -> int | None:
        """Temp number of a spare already in the master, found by its part number (or SAP / SPF number when
        the spare has no part number). The lowest number wins, so a real 5xxxxx number beats an SAP number."""
        if kind != SPARE or not self.plant_codes:
            return None
        prefix, _, value = key.partition(":")
        part_number = func.upper(func.regexp_replace(func.trim(master.c.manufacturers_part_number), r"\s+", " ", "g"))
        column = {"PN": part_number,
                  "SAP": master.c.sap_material_number,
                  "SPF": func.upper(master.c.old_material_number_spf_number)}.get(prefix)
        if column is None:
            return None
        temp = master.c.material_temp_number
        return self.db.execute(
            select(temp).where(*self._master_rows(kind), column == value, temp.is_not(None)).order_by(temp).limit(1)
        ).scalar()

    def _sequence(self, kind: str) -> NumberSequence:
        if kind not in self._seq:
            self.db.execute(
                insert(NumberSequence)
                .values(scope=SEQUENCE_SCOPE, kind=kind, last_value=self.start[kind] - 1)
                .on_conflict_do_nothing(constraint="uq_sequence_scope_kind")
            )
            seq = self.db.execute(
                select(NumberSequence)
                .where(NumberSequence.scope == SEQUENCE_SCOPE, NumberSequence.kind == kind)
                .with_for_update()
            ).scalar_one()
            highest = self._master_max(kind)  # read under the lock -> never below a number already issued
            if highest is not None and highest > seq.last_value:
                seq.last_value = highest
            self._seq[kind] = seq
        return self._seq[kind]

    def _get(self, kind: str, key: str) -> int:
        cache_key = (kind, key)
        if cache_key in self._cache:
            return self._cache[cache_key]
        seq = self._sequence(kind)  # lock first, then look up -> no race between lookup and insert
        existing = self.db.execute(
            select(MaterialNumber.temp_number).where(
                MaterialNumber.scope == self.scope, MaterialNumber.kind == kind, MaterialNumber.item_key == key)
        ).scalar_one_or_none()
        if existing is None:
            existing = self._master_number(kind, key)
            if existing is None:
                seq.last_value += 1
                existing = seq.last_value
                self.new_numbers += 1
            self.db.add(MaterialNumber(scope=self.scope, kind=kind, item_key=key, temp_number=existing,
                                       first_job_id=self.job_id))
        self._cache[cache_key] = existing
        return existing

    def equipment(self, key: str) -> int:
        return self._get(EQUIPMENT, key)

    def spare(self, key: str) -> int:
        return self._get(SPARE, key)
