"""Adds the lines of a conversion to the material master (material_master_import).

One master row per temp number and planning plant: a line whose temp number is already in the master
for that plant (an earlier upload, or the same spare under two tags) is not added again.
"""
from __future__ import annotations

from dataclasses import replace

from sqlalchemy import case, func, insert, select
from sqlalchemy.orm import Session

from ..models import material_master_import as master
from .bom_builder import BomResult


def _str(value) -> str | None:
    return None if value is None else str(value)


def _qty(value):
    return value if isinstance(value, (int, float)) else None


def _spf(value) -> str | None:
    """OLD MATERIAL NUMBER/SPF NUMBER for comparing: exact text, only case and surrounding spaces ignored."""
    text = str(value).strip().upper() if value is not None else ""
    return text or None


def with_master_descriptions(db: Session, result: BomResult, plant_code: str | None) -> BomResult:
    """The result for the Working and Submission templates: a SPARE line whose MATERIAL TEMP NUMBER and
    OLD MATERIAL NUMBER/SPF NUMBER both match a material master record shows that record's material description
    (a row of the same planning plant first, else of another plant). Equipment lines, spares without a match and
    master rows without a description keep the SPIR description. Called before save_to_master(), so only records
    that already existed are used. The result itself (master rows, Parts Master lines, warnings) is not changed."""
    temps = {ln.temp_number for ln in result.lines
             if ln.category == "L" and isinstance(ln.temp_number, int) and _spf(ln.old_material_number)}
    if not temps:
        return result
    plant = master.c.maintenance_planning_plant
    rows = db.execute(
        select(master.c.material_temp_number, master.c.old_material_number_spf_number, master.c.material_description)
        .where(master.c.material_temp_number.in_(temps),
               master.c.old_material_number_spf_number.is_not(None),
               func.nullif(func.trim(master.c.material_description), "").is_not(None))
        .order_by(case((plant == plant_code, 0), else_=1), plant)
    ).all()
    descriptions: dict[tuple[int, str], str] = {}
    for temp, spf, description in rows:
        if _spf(spf):
            descriptions.setdefault((temp, _spf(spf)), description)
    if not descriptions:
        return result

    def described(ln):
        key = (ln.temp_number, _spf(ln.old_material_number))
        return replace(ln, description=descriptions[key]) if ln.category == "L" and key in descriptions else ln

    return replace(result, lines=[described(ln) for ln in result.lines])


def save_to_master(db: Session, result: BomResult, plant_code: str | None) -> int:
    """Insert the new lines; returns how many rows were added."""
    plant = master.c.maintenance_planning_plant
    known = set(db.scalars(
        select(master.c.material_temp_number).where(plant == plant_code if plant_code else plant.is_(None))
    ))
    rows = []
    for line in result.lines:
        temp = line.temp_number
        if not isinstance(temp, int) or temp in known:  # a non-numeric SAP number cannot be a temp number
            continue
        known.add(temp)
        rows.append({
            "material_temp_number": temp,
            "material_type_category": line.type_category,  # B / L, or N (spare with a 3/8 SAP number)
            "material_is_equipment_indicator": line.equipment_indicator == "YES",
            "old_material_number_spf_number": line.old_material_number,
            "material_description": line.description,
            "maintenance_planning_plant": plant_code,
            "base_unit_of_measure": line.uom,
            # full part number (the template cuts it to 35 characters and keeps the rest in CDC_ADD INFORMATION)
            "manufacturers_part_number": line.add_information or line.mfr_part_number,
            "manufacturer_name": line.mfr_name,
            "cdc_spir_number": line.spir_number,
            "reorder_point_minimum_qty": _qty(line.min_qty),
            "maximum_stock_level_max_qty": _qty(line.max_qty),
            "sap_material_number": _str(line.sap_material_number),
        })
    if rows:
        db.execute(insert(master), rows)
    return len(rows)
