"""Material master (material_master_import): continue numbering, reuse numbers, save new lines.

Runs against PostgreSQL (TEST_DATABASE_URL, wiped by these tests).
"""
import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import Base, engine

try:
    with engine.connect():
        pass
except OperationalError:  # pragma: no cover
    pytest.skip("PostgreSQL test database not reachable", allow_module_level=True)

from app.models import material_master_import as master  # noqa: E402
from app.services.bom_builder import DUKHAN, InMemoryAllocator, build_bom  # noqa: E402
from app.services.input_reader import read_input  # noqa: E402
from app.services.material_master import save_to_master  # noqa: E402
from app.services.numbering import DbAllocator  # noqa: E402


@pytest.fixture
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def add_master(db, plant, temp, equipment, sap=None, spf=None):
    db.execute(insert(master).values(
        material_temp_number=temp, maintenance_planning_plant=plant, material_is_equipment_indicator=equipment,
        material_type_category="B" if equipment else "L", sap_material_number=sap,
        old_material_number_spf_number=spf))


def test_numbering_continues_after_master(db):
    add_master(db, "T1", 40010, True)
    add_master(db, "T1", 500020, False)
    add_master(db, "T1", 80012771, False, sap="80012771")  # SAP number in the temp column - ignored
    add_master(db, "T2", 40500, True)                       # other plant - counts too (no duplicates)
    add_master(db, "T2", 40500, True)                       # duplicate value - ignored
    add_master(db, "T2", 500030, False)
    alloc = DbAllocator(db, "DUKHAN:T1", ["T1"])
    assert alloc.equipment("TAG:NEW") == 40501
    assert alloc.spare("DESC:NEW") == 500031


def test_spare_reuses_master_number(db):
    add_master(db, "T1", 500005, False, sap="123")
    add_master(db, "T1", 500006, False, spf="ABC-1")
    add_master(db, "T2", 500007, False, spf="XYZ")
    alloc = DbAllocator(db, "DUKHAN:T1", ["T1"])
    assert alloc.spare("SAP:123") == 500005
    assert alloc.spare("SPF:ABC-1") == 500006
    assert alloc.spare("SPF:XYZ") == 500008  # only found for plant T2 -> new number after the highest
    assert alloc.new_numbers == 1


def test_save_to_master_adds_new_lines_once(db, sample_bytes):
    result = build_bom(read_input(sample_bytes), DUKHAN, "T1", InMemoryAllocator(), {})
    temps = {line.temp_number for line in result.lines}
    assert save_to_master(db, result, "T1") == len(temps)
    assert save_to_master(db, result, "T1") == 0  # same upload again -> nothing new
    count = db.execute(select(func.count()).select_from(master)
                       .where(master.c.maintenance_planning_plant == "T1")).scalar()
    assert count == len(temps)
    eq = db.execute(select(master).where(master.c.material_temp_number == 40001)).one()
    assert eq.material_type_category == "B" and eq.material_is_equipment_indicator is True


def test_spare_reuses_master_number_by_part_number(db):
    db.execute(insert(master).values(material_temp_number=500010, maintenance_planning_plant="T1",
                                     material_is_equipment_indicator=False, manufacturers_part_number="1SBL  137001r1110"))
    add_master(db, "T1", 500020, False)
    alloc = DbAllocator(db, "DUKHAN:T1", ["T1"])
    assert alloc.spare("PN:1SBL 137001R1110") == 500010
    assert alloc.spare("PN:NEW-PART") == 500021
    db.commit()
    again = DbAllocator(db, "DUKHAN:T1", ["T1"])  # next upload
    assert again.spare("PN:NEW-PART") == 500021
    assert again.spare("PN:OTHER-PART") == 500022
