"""Parts Master -> Excel, laid out exactly like the MATERIAL MASTER sheet of the submission template.

The template's own MATERIAL MASTER sheet is used (header block rows 1-5 with its colours, widths and field
codes); the other sheets are removed. Data starts at row 6 with the same borders and frozen header as the
submission template. Columns the Parts Master does not hold (safety stock, criticality, price, ...) stay empty.
"""
from __future__ import annotations

import io
import re

import openpyxl
from sqlalchemy.orm import Session

from ..config import get_settings
from ..seed import country_map
from .excel_writer import SUBMISSION_FIRST_DATA_ROW, _black_text, _border_table, _header_index, _put, _sheet
from .input_reader import norm_header

SHEET = "MATERIAL MASTER"

# template heading -> Parts Master field
COLUMNS = {
    "MATERIAL TEMP NUMBER": "material_temp_number",
    "MATERIAL TYPEVCATEGORY": "material_category",
    "OLD MATERIAL NUMBER/SPF NUMBER": "old_material_number",
    "MATERIAL DESCRIPTION": "description",
    "MAINTENANCE PLANNING PLANT": "planning_plant",
    "BASE UNIT OF MEASURE(T006)": "uom",
    "MANUFACTURERS PART NUMBER": "part_number",
    "MANUFACTURER NAME": "manufacturer_name",
    "MATERIAL IS AN EQUIPMENT INDICATOR": "equipment_indicator",
    "MANUFACTURER COUNTRY CODE": "country_code",
    "CDC_SPIR NUMBER": "spir",
    "REORDER POINT (MINIMUM QTY)": "min_qty",
    "MAXIMUM STOCK LEVEL(MAX QTY)": "max_qty",
    "SAP MATERIAL NUMBER": "sap_material_number",
}
NUMERIC = {"material_temp_number", "sap_material_number", "min_qty", "max_qty"}


def _value(field: str, value):
    """Whole numbers become Excel numbers (temp / SAP numbers, quantities); everything else stays text."""
    if value is None or value == "":
        return None
    if field in NUMERIC and isinstance(value, str):
        if value.isdigit():
            return int(value)
        if re.fullmatch(r"\d+\.\d+", value):
            f = float(value)
            return int(f) if f.is_integer() else f
    return value


def _country_codes(names: str | None, codes: dict[str, str]) -> str | None:
    """'QATAR' -> 'QA'; a merged 'QATAR, INDIA' -> 'QA, IN'. Unknown names are left out."""
    if not names:
        return None
    found = [codes.get(n.strip().upper()) for n in names.split(",")]
    return ", ".join(dict.fromkeys(c for c in found if c)) or None


def export_parts(db: Session, rows: list[dict]) -> bytes:
    wb = openpyxl.load_workbook(get_settings().submission_dukhan)  # both templates share this sheet layout
    ws = _sheet(wb, SHEET)
    for other in [s for s in wb.worksheets if s is not ws]:
        wb.remove(other)

    idx = _header_index(ws)
    targets = [(idx[norm_header(h)], f) for h, f in COLUMNS.items() if norm_header(h) in idx]

    # clear anything below the header block (the template carries sample values)
    for row in ws.iter_rows(min_row=SUBMISSION_FIRST_DATA_ROW):
        for c in row:
            c.value = None

    codes = country_map(db)
    for i, part in enumerate(rows):
        r = SUBMISSION_FIRST_DATA_ROW + i
        record = {**part, "country_code": _country_codes(part.get("country_name"), codes)}
        for col, field in targets:
            value = _value(field, record.get(field))
            if value is not None:
                _put(ws, r, col, value)

    _border_table(ws, SUBMISSION_FIRST_DATA_ROW, len(rows))
    _black_text(ws, SUBMISSION_FIRST_DATA_ROW, len(rows))
    ws.freeze_panes = f"A{SUBMISSION_FIRST_DATA_ROW}"
    wb.active = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
