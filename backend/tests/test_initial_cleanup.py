"""One-time cleanup of the tester's data at the tester's first extraction (services/initial_cleanup.py).

Runs against PostgreSQL (TEST_DATABASE_URL, wiped by these tests).
"""
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import OperationalError

from app.database import Base, SessionLocal, engine

try:
    with engine.connect():
        pass
except OperationalError:  # pragma: no cover
    pytest.skip("PostgreSQL test database not reachable", allow_module_level=True)

from app.main import app  # noqa: E402
from app.manage import main as manage  # noqa: E402
from app.models import (ConversionJob, ExtractedLine, MaterialNumber, NumberSequence, OneTimeTask,  # noqa: E402
                        Plant, User, material_master_import as master)
from app.services.converter import convert  # noqa: E402
from app.services.initial_cleanup import TASK_NAME, run_tester_cleanup_once  # noqa: E402

PASSWORD = "correct-horse-1"
IMPORTED_TEMP = 777001  # a row "imported in pgAdmin": no conversion inserted it


def login(c, username):
    assert c.post("/api/auth/login", json={"username": username, "password": PASSWORD}).status_code == 200


def upload(c, sample_bytes, plant):
    r = c.post("/api/jobs", data={"plant_type": plant.plant_type, "plant_id": str(plant.id)},
               files={"file": ("in.xlsx", sample_bytes, "application/octet-stream")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def master_temps(job_id):
    """Temp numbers of the master rows inserted by this conversion (same transaction as its history row)."""
    with engine.connect() as conn:
        return set(conn.execute(text(
            "SELECT m.material_temp_number FROM material_master_import m "
            "JOIN conversion_jobs j ON m.xmin::text = j.xmin::text WHERE j.id = :id"), {"id": job_id}).scalars())


def line_temps(job_id, category):
    with SessionLocal() as db:
        return {int(t) for t in db.scalars(select(ExtractedLine.temp_number).where(
            ExtractedLine.job_id == job_id, ExtractedLine.category == category))}


def counters():
    with SessionLocal() as db:
        return {s.kind: s.last_value for s in db.scalars(select(NumberSequence).where(NumberSequence.scope == "ALL"))}


@pytest.fixture(scope="module")
def setup(sample_bytes):
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        mp = pytest.MonkeyPatch()
        for username, name in (("tester", "Tester"), ("alice", "Alice")):
            mp.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
            manage(["create-user", username, "--password-stdin", "--name", name])
        mp.undo()
        with SessionLocal() as db:
            dukhan = db.scalars(select(Plant).where(Plant.plant_type == "DUKHAN")).first()
            other = db.scalars(select(Plant).where(Plant.plant_type == "OTHER")).first()
            db.expunge_all()
        # the tester's data from before the cleanup existed (created without going through the API hook)
        with SessionLocal() as db:
            old_job = convert(db, plant_type="DUKHAN", plant=dukhan, content=sample_bytes, filename="old.xlsx",
                              user_name="Tester").id
        # a master row imported outside the app, in its own transaction
        with engine.begin() as conn:
            conn.execute(insert(master).values(material_temp_number=IMPORTED_TEMP, maintenance_planning_plant=dukhan.code,
                                               material_is_equipment_indicator=False, material_type_category="L",
                                               manufacturers_part_number="IMPORTED-PN"))
        login(c, "alice")
        alice_job = upload(c, sample_bytes, other)
        yield {"client": c, "dukhan": dukhan, "old_job": old_job, "alice_job": alice_job}


def test_other_users_never_trigger_the_cleanup(setup):
    with SessionLocal() as db:
        assert db.get(OneTimeTask, TASK_NAME) is None          # alice's upload did not run it
        assert db.get(ConversionJob, setup["old_job"]) is not None


def test_first_tester_extraction_cleans_once_and_keeps_everything_else(setup, sample_bytes):
    c, old_job, alice_job = setup["client"], setup["old_job"], setup["alice_job"]
    old_master = master_temps(old_job)
    old_eq_max = max(line_temps(old_job, "B"))
    alice_master = master_temps(alice_job)
    before = counters()
    assert old_master and alice_master

    login(c, "tester")
    new_job = upload(c, sample_bytes, setup["dukhan"])

    with SessionLocal() as db:
        # the tester's earlier conversion, its Parts Master lines and numbering memory are gone
        assert db.get(ConversionJob, old_job) is None
        assert db.scalar(select(func.count()).select_from(ExtractedLine).where(ExtractedLine.job_id == old_job)) == 0
        assert db.scalar(select(func.count()).select_from(MaterialNumber)
                         .where(MaterialNumber.first_job_id == old_job)) == 0
        # its master rows are gone, the imported row and the other user's data are kept
        plant_temps = set(db.scalars(select(master.c.material_temp_number)
                                     .where(master.c.maintenance_planning_plant == setup["dukhan"].code)))
        assert IMPORTED_TEMP in plant_temps
        # numbers the counters generated are never seen again (SAP numbers are the materials' own numbers)
        generated = {t for t in old_master if t < 1_000_000}
        assert generated and not generated & plant_temps
        assert db.get(ConversionJob, alice_job) is not None
        assert master_temps(alice_job) == alice_master
        task = db.get(OneTimeTask, TASK_NAME)
        assert task.done_by == "tester" and task.summary["conversions"] == 1 and task.summary["master_rows"] > 0

    # counters are not reset: the new conversion never reuses a number issued before the cleanup
    after = counters()
    assert all(after[k] >= before[k] for k in before)
    assert min(line_temps(new_job, "B")) > old_eq_max
    setup["new_job"] = new_job


def test_later_tester_extractions_delete_nothing(setup, sample_bytes):
    c, first = setup["client"], setup["new_job"]
    with SessionLocal() as db:
        done_at = db.get(OneTimeTask, TASK_NAME).done_at
    first_master = master_temps(first)
    numbering = _numbering_rows()

    second = upload(c, sample_bytes, setup["dukhan"])

    with SessionLocal() as db:
        assert db.get(ConversionJob, first) is not None
        assert db.get(OneTimeTask, TASK_NAME).done_at == done_at        # did not run again
    assert master_temps(first) == first_master
    assert numbering <= _numbering_rows()                                # numbering history intact
    # same file, same plant -> the numbers assigned after the cleanup are reused, not reset
    assert line_temps(second, "B") == line_temps(first, "B")
    assert line_temps(second, "L") == line_temps(first, "L")


def test_cleanup_never_runs_again_after_a_restart(setup):
    # the marker lives in the database, so a fresh session (restart / new login) still sees it
    with SessionLocal() as db:
        tester = db.scalars(select(User).where(User.username == "tester")).one()
        assert run_tester_cleanup_once(db, tester) is None
        assert db.get(ConversionJob, setup["new_job"]) is not None


def _numbering_rows():
    with SessionLocal() as db:
        return {(m.scope, m.kind, m.item_key, m.temp_number) for m in db.scalars(select(MaterialNumber))}
