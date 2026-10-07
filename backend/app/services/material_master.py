"""Adds the lines of a conversion to the material master (material_master_import).

One master row per temp number and planning plant: a line whose temp number is already in the master
for that plant (an earlier upload, or the same spare under two tags) is not added again.
"""
from __future__ import annotations

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from ..models import material_master_import as master
from .bom_builder import BomResult


def _str(value) -> str | None:
    return None if value is None else str(value)


def _qty(value):
    return value if isinstance(value, (int, float)) else None


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
            "material_type_category": line.category,
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
