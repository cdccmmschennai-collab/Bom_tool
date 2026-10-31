"""Material Temp Number allocation stored in PostgreSQL.

* A temp number is reused ONLY for the same Maintenance Planning Plant + Project Number: an item (part number,
  MESC number, make + model, cabinet signature, tag, SAP / SPF number, description) seen before in that plant and
  project - numbering memory under scope "<plant>|<PROJECT>", or a material master row with the same plant and
  project - gets the same number again. The same plant with another project, or another plant, gets a new number.
* A new temp number is never one that was already issued, in any plant or project: there is one running sequence
  per kind (equipment / spare) for everything, and it always continues after the highest number already in the
  material master (material_master_import) - gaps and duplicate values there are ignored.
* Equipment and spares never share a number, even with the same part number: each kind is looked up only
  among its own kind (memory and master) and numbered from its own counter (4xxxx / 5xxxxx).
* The sequence row is locked (SELECT ... FOR UPDATE) for the whole conversion, so two users
  converting at the same time can never receive the same number.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import MaterialNumber, NumberSequence, material_master_import as master
from .bom_builder import description_key

EQUIPMENT = "EQUIPMENT"
SPARE = "SPARE"
SEQUENCE_SCOPE = "ALL"  # new numbers come from one sequence per kind, shared by every plant and project


def normalize_project(project_number: str) -> str:
    return project_number.strip().upper()


def numbering_scope(plant_code: str, project_number: str) -> str:
    """Numbering memory scope: '<plant>|<PROJECT>' (max 4 + 1 + 25 = 30 characters)."""
    return f"{plant_code}|{normalize_project(project_number)}"


class DbAllocator:
    def __init__(self, db: Session, plant_code: str, project_number: str):
        s = get_settings()
        self.db = db
        self.plant_code = plant_code
        self.project = normalize_project(project_number)
        self.scope = numbering_scope(plant_code, project_number)
        self.start = {EQUIPMENT: s.equipment_start, SPARE: s.spare_start}
        self._cache: dict[tuple[str, str], int] = {}
        self._seq: dict[str, NumberSequence] = {}
        self.new_numbers = 0
        self.job_id: int | None = None

    def _master_rows(self, kind: str):
        """Master rows of the same plant + project and the same kind (equipment / spare)."""
        is_eq = master.c.material_is_equipment_indicator
        return (master.c.maintenance_planning_plant == self.plant_code,
                func.upper(func.trim(master.c.project_number)) == self.project,
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
        """Temp number already in the master for this item - only from rows of the same plant + project.
        Part numbers for equipment and spares, SAP / SPF numbers for spares without a part number. The lowest
        number wins, so a real 4xxxx / 5xxxxx number beats an SAP number. PNDESC (part number used with several
        descriptions): part number and description must both match."""
        prefix, _, value = key.partition(":")
        temp = master.c.material_temp_number
        if prefix == "PNDESC":  # part number + description: the description is compared as in description_key()
            pn, _, desc = value.partition("|")
            column = func.upper(func.regexp_replace(func.trim(master.c.manufacturers_part_number), r"\s+", " ", "g"))
            rows = self.db.execute(
                select(temp, master.c.material_description)
                .where(*self._master_rows(kind), column == pn, temp.is_not(None)).order_by(temp)
            ).all()
            return next((t for t, d in rows if description_key(d) == desc), None)
        if prefix == "PN":
            column = func.upper(func.regexp_replace(func.trim(master.c.manufacturers_part_number), r"\s+", " ", "g"))
        elif kind == SPARE and prefix in ("SAP", "SPF"):
            column = {"SAP": master.c.sap_material_number,
                      "SPF": func.upper(master.c.old_material_number_spf_number)}[prefix]
        else:
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
        scope = self.scope  # every key: reused only within the same plant + project
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
