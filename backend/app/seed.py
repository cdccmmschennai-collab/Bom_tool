"""Seed / sync reference data at start-up.

* plants:        synced from app/resources/plants.json (edit that file and restart - no admin screen).
                 Plants removed from the file are hidden from the dropdown (kept for history).
* country_codes: loaded once from app/resources/COUNTRY_REFERENCE.xlsx (sheet 1: Country | Code).
"""
from __future__ import annotations

import json
import logging

import openpyxl
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import CountryCode, Plant

log = logging.getLogger(__name__)


def sync_plants(db: Session) -> None:
    data = json.loads(get_settings().plants_seed.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for order, item in enumerate(data):
        code = str(item["code"]).strip().upper()
        plant_type = str(item["plant_type"]).strip().upper()
        if plant_type not in ("DUKHAN", "OTHER"):
            raise ValueError(f"plants.json: plant_type must be DUKHAN or OTHER (got {plant_type!r})")
        if len(code) > 4:
            raise ValueError(f"plants.json: plant code {code!r} is longer than 4 characters (IWERK)")
        seen.add(code)
        plant = db.execute(select(Plant).where(Plant.code == code)).scalar_one_or_none()
        if plant is None:
            plant = Plant(code=code)
            db.add(plant)
        plant.name = str(item.get("name") or code).strip()
        plant.plant_type = plant_type
        plant.active = bool(item.get("active", True))
        plant.sort_order = order
    for plant in db.execute(select(Plant)).scalars():
        if plant.code not in seen:
            plant.active = False
    db.commit()


def load_country_reference(db: Session, force: bool = False) -> int:
    if not force and db.execute(select(func.count(CountryCode.id))).scalar_one() > 0:
        return 0
    wb = openpyxl.load_workbook(get_settings().country_reference, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = []
    for name, code, *_ in ws.iter_rows(min_row=1, values_only=True):
        # header rows ("HERLD | COUNTRY CODE- T005" and "Country | Code") are skipped
        if not name or not code or str(name).strip().upper() in ("HERLD", "COUNTRY"):
            continue
        name_s, code_s = str(name).strip(), str(code).strip().upper()
        rows.append(CountryCode(name=name_s, name_upper=name_s.upper(), code=code_s))
    wb.close()
    db.execute(delete(CountryCode))
    db.add_all(rows)
    db.commit()
    log.info("Loaded %d country codes", len(rows))
    return len(rows)


def country_map(db: Session) -> dict[str, str]:
    result: dict[str, str] = {}
    for name_upper, code in db.execute(select(CountryCode.name_upper, CountryCode.code)):
        result.setdefault(name_upper, code)  # first one wins for duplicated names (e.g. 'Congo')
    return result
