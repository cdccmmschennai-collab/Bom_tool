"""Material Temp Number allocation stored in PostgreSQL.

* A new temp number is never one that was already issued, in any plant: there is one running sequence per
  kind (equipment / spare) for all plants, and it always continues after the highest number already in the
  material master (material_master_import) - gaps and duplicate values there are ignored.
* One manufacturer part number = one temp number, for equipment and spares, across ALL plants: a part
  number seen before (numbering memory under scope "ALL", or manufacturers_part_number in the master)
  gets the same number again. From another plant's master rows only numbers in the kind's own temp range
  are taken, so an SAP number stored there is never handed to a Dukhan line.
* Equipment and spares never share a number, even with the same part number: each kind is looked up only
  among its own kind (memory and master) and numbered from its own counter (4xxxx / 5xxxxx).
* Every other key is reused per numbering scope (plant based - see Settings.numbering_scope): equipment
  without a part number by its tag, spares without a part number by SAP / SPF number or description.
* The sequence row is locked (SELECT ... FOR UPDATE) for the whole conversion, so two users
  converting at the same time can never receive the same number.
"""
from __future__ import annotations

from sqlalchemy import and_, func, or_, select
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

    def _in_range(self, kind: str):
        """The kind's temp number range, e.g. 40001-99999 for equipment and 500001-999999 for spares.
        SAP numbers (8 digits) stored in the temp column are outside both."""
        start = self.start[kind]
        temp = master.c.material_temp_number
        return (temp >= start, temp < 10 ** len(str(start)))

    def _master_max(self, kind: str) -> int | None:
        """Highest temp number in the whole master (all plants) within the kind's range."""
        temp = master.c.material_temp_number
        return self.db.execute(select(func.max(temp)).where(*self._in_range(kind))).scalar()

    def _master_number(self, kind: str, key: str) -> int | None:
        """Temp number already in the master for this item. Part numbers (equipment and spares) are looked up
        in every plant - another plant's row only when its number is in the kind's range; SAP / SPF numbers
        (spares without a part number) only in the scope's plants. The lowest number wins, so a real
        4xxxx / 5xxxxx number beats an SAP number."""
        prefix, _, value = key.partition(":")
        temp = master.c.material_temp_number
        if prefix == "PN":
            is_eq = master.c.material_is_equipment_indicator
            column = func.upper(func.regexp_replace(func.trim(master.c.manufacturers_part_number), r"\s+", " ", "g"))
            rows = (is_eq.is_(True) if kind == EQUIPMENT else is_eq.is_not(True),
                    or_(master.c.maintenance_planning_plant.in_(self.plant_codes), and_(*self._in_range(kind))))
        else:
            if kind != SPARE or not self.plant_codes:
                return None
            column = {"SAP": master.c.sap_material_number,
                      "SPF": func.upper(master.c.old_material_number_spf_number)}.get(prefix)
            if column is None:
                return None
            rows = self._master_rows(kind)
        return self.db.execute(
            select(temp).where(*rows, column == value, temp.is_not(None)).order_by(temp).limit(1)
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
        scope = SEQUENCE_SCOPE if key.startswith("PN:") else self.scope  # part numbers: one number for all plants
        existing = self.db.execute(
            select(MaterialNumber.temp_number).where(
                MaterialNumber.scope == scope, MaterialNumber.kind == kind, MaterialNumber.item_key == key)
        ).scalar_one_or_none()
        if existing is None:
            existing = self._master_number(kind, key)
            if existing is None:
                seq.last_value += 1
                existing = seq.last_value
                self.new_numbers += 1
            self.db.add(MaterialNumber(scope=scope, kind=kind, item_key=key, temp_number=existing,
                                       first_job_id=self.job_id))
        self._cache[cache_key] = existing
        return existing

    def equipment(self, key: str) -> int:
        return self._get(EQUIPMENT, key)

    def spare(self, key: str) -> int:
        return self._get(SPARE, key)
