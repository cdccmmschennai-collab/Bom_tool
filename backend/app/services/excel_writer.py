"""Write a BomResult into the Dukhan / Other-plant template.

The template file is loaded as-is and cell VALUES are written, so header colours, fonts,
borders and widths stay exactly as in the template. No fills or conditional formatting are added.
Every cell of the filled data table (all header columns x all data rows, empty or not) gets a thin
border (like the template's header cells), and the header block is frozen so it stays visible while
scrolling. All text in the data table is black (the template pre-colours a few LEN() cells red).
"""
from __future__ import annotations

import io
from copy import copy
from pathlib import Path

import openpyxl
from openpyxl.styles import Border, Color, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .bom_builder import DUKHAN, BomResult
from .input_reader import norm_header

BOM_SHEET = "BOM WORKING TEMPLATE"
TAG_SHEET = "SPIR TAG vs SUBMT"
BOM_FIRST_DATA_ROW = 6   # rows 1-5 are the template header block
TAG_FIRST_DATA_ROW = 3   # rows 1-2 are the template header block

_THIN = Side(style="thin")
VALUE_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
BLACK = "FF000000"

# template header text -> BomLine attribute ("=LEN:<header>" writes a live LEN() formula)
BOM_COLUMNS: dict[str, str] = {
    "SERIAL NUMBER": "serial",
    "SAP MATERIAL NUMBER": "sap_material_number",          # Dukhan only
    "MATERIAL TEMP NUMBER": "temp_number",
    "MATERIAL TYPEVCATEGORY": "category",
    "OLD MATERIAL NUMBER/SPF NUMBER": "old_material_number",
    "LEN(OLD MAT/SPF NUMBER = 18)": "=LEN:OLD MATERIAL NUMBER/SPF NUMBER",
    "MATERIAL DESCRIPTION": "description",
    "LEN(MAT.DESC = 40)": "=LEN:MATERIAL DESCRIPTION",
    "MAINTENANCE PLANNING PLANT": "planning_plant",
    "BASE UNIT OF MEASURE(T006)": "uom",
    "MANUFACTURERS PART NUMBER": "mfr_part_number",
    "LEN(MFR PART NUMBER = 18)": "=LEN:MANUFACTURERS PART NUMBER",
    "MANUFACTURER NAME": "mfr_name",
    "LEN(MANUFACTURER=30)": "=LEN:MANUFACTURER NAME",
    "MATERIAL IS AN EQUIPMENT INDICATOR": "equipment_indicator",
    "BOM HEADER NUMBER": "bom_header_number",
    "QUANTITY": "quantity",
    "POSITION NUMBER": "position_number",
    "CDC_SPIR NUMBER": "spir_number",
    "DELIVERY TIME IN WEEKS": "delivery_weeks",
    "MANUFACTURER COUNTRY CODE": "country_code",
    "MM REQUIREMENT MOVING AVERAGE PRICE": "price",
    "CDC_ADD INFORMATION": "add_information_text",
    "REORDER POINT (MINIMUM QTY)": "min_qty",
    "MAXIMUM STOCK LEVEL(MAX QTY)": "max_qty",
    "MANUFACTURER COUNTRY NAME": "country_name",
    "CURRENCY CODE REF": "currency",
}
# Columns that the logic says to leave empty are simply not written:
# EXTERNAL NUMBER ASSIGNED FOR ASSEMBLY, MESC/SPF_REF, SAFETY STOCK, CRITICALITY, MM MATERIAL TYPE,
# MM MATERIAL GROUP, PO TEXT, CDC_SAP CODE REMARKS, CDC_CONSTRUCTION TYPE STATUS, ASSEMBLY,
# BOM HEADER-REMARKS, PRD / QC columns.

TAG_COLUMNS = ["EQFNR", "SUBMT", "SPIR NO", "REV", "HERST", "TYPBZ", "MAPAR", "SERGE", "SPIR TYPE", "REMARKS"]
TAG_ATTRS = ["tag", "submt", "spir_no", "rev", "herst", "typbz", "mapar", "serge", "spir_type", None]


class TemplateError(RuntimeError):
    pass


def _put(ws: Worksheet, row: int, col: int, value) -> None:
    ws.cell(row, col, value)


def _border_table(ws: Worksheet, first_row: int, row_count: int) -> None:
    """Border every cell of the data table - all header columns of every data row, empty cells
    included. The template pre-formats a few blank rows below with borders; those are dropped so
    the grid ends at the last data row. Only the border is touched."""
    last_row = first_row + row_count - 1
    last_col = max(_header_index(ws).values())
    for row in ws.iter_rows(min_row=first_row, max_row=max(ws.max_row, last_row)):
        for c in row:
            if c.row <= last_row and c.column <= last_col:
                c.border = VALUE_BORDER
            elif c.has_style:
                c.border = Border()


def _black_text(ws: Worksheet, first_row: int, row_count: int) -> None:
    """Make the text of every data-table cell black. Only the font colour changes - font name, size,
    bold etc. stay as in the template. The header block is not touched."""
    last_col = max(_header_index(ws).values())
    for row in ws.iter_rows(min_row=first_row, max_row=first_row + row_count - 1, max_col=last_col):
        for c in row:
            color = c.font.color
            if color is None or (color.type == "rgb" and color.rgb == BLACK):
                continue  # already black (no colour = Excel's automatic black)
            font = copy(c.font)
            font.color = Color(rgb=BLACK)
            c.font = font


def _sheet(wb: openpyxl.Workbook, name: str) -> Worksheet:
    for ws in wb.worksheets:
        if ws.title.strip().upper() == name.upper():
            return ws
    raise TemplateError(f"Sheet '{name}' not found in the template.")


def set_active_sheet(wb: openpyxl.Workbook, ws: Worksheet) -> None:
    """Open the workbook on `ws` with only that tab selected.

    `wb.active = ...` does not unselect the tab the template was saved on, and two selected tabs make
    Excel open the file in [Group] mode - which disables Filter and Sort.
    """
    for sheet in wb.worksheets:
        sheet.sheet_view.tabSelected = sheet is ws
    wb.active = wb.worksheets.index(ws)


def _header_index(ws: Worksheet, row: int = 1) -> dict[str, int]:
    return {norm_header(c.value): c.column for c in ws[row] if c.value is not None}


def _ensure_spir_type_column(ws: Worksheet) -> None:
    """The template's tag sheet has no SPIR TYPE column - insert it before REMARKS,
    copying the header style of the neighbouring column (no new colours)."""
    idx = _header_index(ws)
    if norm_header("SPIR TYPE") in idx:
        return
    remarks = idx.get(norm_header("REMARKS"))
    if remarks is None:
        remarks = ws.max_column + 1
    else:
        ws.insert_cols(remarks)
        # shift column widths right (openpyxl does not move them)
        for col in range(ws.max_column, remarks, -1):
            src = ws.column_dimensions[get_column_letter(col - 1)]
            ws.column_dimensions[get_column_letter(col)].width = src.width
    for r, text in ((1, "SPIR TYPE"), (2, "SPIR TYPE")):
        cell = ws.cell(r, remarks, text)
        cell._style = copy(ws.cell(r, remarks - 1)._style)
    ws.column_dimensions[get_column_letter(remarks)].width = max(
        ws.column_dimensions[get_column_letter(remarks - 1)].width or 10, 26)


def write_workbook(result: BomResult, plant_type: str, template_path: Path) -> bytes:
    wb = openpyxl.load_workbook(template_path)

    # ---- sheet 1: BOM WORKING TEMPLATE
    ws = _sheet(wb, BOM_SHEET)
    idx = _header_index(ws)
    targets: list[tuple[int, str]] = []
    for header, attr in BOM_COLUMNS.items():
        col = idx.get(norm_header(header))
        if col is None:
            if header == "SAP MATERIAL NUMBER" and plant_type != DUKHAN:
                continue  # column exists only in the Dukhan template
            raise TemplateError(f"Column '{header}' not found in the {plant_type} template.")
        targets.append((col, attr))

    for i, line in enumerate(result.lines):
        r = BOM_FIRST_DATA_ROW + i
        for col, attr in targets:
            if attr.startswith("=LEN:"):
                src_col = idx[norm_header(attr[5:])]
                _put(ws, r, col, f"=LEN({get_column_letter(src_col)}{r})")
            else:
                value = getattr(line, attr)
                if value is not None:
                    _put(ws, r, col, value)

    # ---- sheet 2: SPIR TAG vs SUBMT
    ws2 = _sheet(wb, TAG_SHEET)
    _ensure_spir_type_column(ws2)
    idx2 = _header_index(ws2)
    for j, tag in enumerate(result.tags):
        r = TAG_FIRST_DATA_ROW + j
        for header, attr in zip(TAG_COLUMNS, TAG_ATTRS):
            if attr is None:
                continue
            value = getattr(tag, attr)
            if value is not None:
                _put(ws2, r, idx2[norm_header(header)], value)

    _border_table(ws, BOM_FIRST_DATA_ROW, len(result.lines))
    _border_table(ws2, TAG_FIRST_DATA_ROW, len(result.tags))
    _black_text(ws, BOM_FIRST_DATA_ROW, len(result.lines))
    _black_text(ws2, TAG_FIRST_DATA_ROW, len(result.tags))

    # freeze the header blocks: rows 1-5 on the BOM sheet, rows 1-2 on the tag sheet
    ws.freeze_panes = f"A{BOM_FIRST_DATA_ROW}"
    ws2.freeze_panes = f"A{TAG_FIRST_DATA_ROW}"

    set_active_sheet(wb, ws)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- submission template
SUBMISSION_FIRST_DATA_ROW = 6  # rows 1-5 are the template header block on every sheet

# Columns not listed are left empty: External Number Assigned for Assembly, Safety Stock,
# Criticality, CDC_SAP CODED REMARK, CDC_CONSTRUCTION TYPE STATUS, CDC_BOM Parts Remark,
# MM requirement material type / group, PO text.
_COMMON = {
    "MATERIAL TEMP NUMBER": "temp_number",
    "MATERIAL TYPEVCATEGORY": "category",
    "OLD MATERIAL NUMBER/SPF NUMBER": "old_material_number",
    "MATERIAL DESCRIPTION": "description",
    "MAINTENANCE PLANNING PLANT": "planning_plant",
    "BASE UNIT OF MEASURE(T006)": "uom",
    "MANUFACTURERS PART NUMBER": "mfr_part_number",
    "MANUFACTURER NAME": "mfr_name",
    "CDC_SPIR NUMBER": "spir_number",
    "CDC_ADD INFORMATION": "add_information_text",
}
SUBMISSION_SHEETS: dict[str, tuple[str, dict[str, str]]] = {
    # sheet -> (which lines, header -> BomLine attribute)
    "BOM HEADER": ("equipment", {
        **_COMMON,
        "MATERIAL IS AN EQUIPMENT INDICATOR": "equipment_indicator",
    }),
    "BOM PARTS": ("spares", {
        "BOM HEADER NUMBER": "bom_header_number",
        **_COMMON,
        "QUANTITY": "quantity",
        "POSITION NUMBER": "position_number",
        "SAP MATERIAL NUMBER": "sap_material_number",
    }),
    "MATERIAL MASTER": ("all", {
        **_COMMON,
        "MATERIAL IS AN EQUIPMENT INDICATOR": "equipment_indicator",
        "DELIVERY TIME IN WEEKS": "delivery_weeks",
        "MANUFACTURER COUNTRY CODE": "country_code",
        "MM REQUIREMENT MOVING AVERAGE PRICE": "price",
        "REORDER POINT (MINIMUM QTY)": "min_qty",
        "MAXIMUM STOCK LEVEL(MAX QTY)": "max_qty",
        "SAP MATERIAL NUMBER": "sap_material_number",
    }),
}


def write_submission(result: BomResult, template_path: Path) -> bytes:
    """Fill the BOM submission template: BOM HEADER = equipment, BOM PARTS = spares (linked to their
    equipment by BOM header number), MATERIAL MASTER = every material."""
    wb = openpyxl.load_workbook(template_path)
    groups = {
        "equipment": [ln for ln in result.lines if ln.equipment_indicator == "YES"],
        "spares": [ln for ln in result.lines if ln.equipment_indicator != "YES"],
        "all": result.lines,
    }
    for name, (group, columns) in SUBMISSION_SHEETS.items():
        ws = _sheet(wb, name)
        idx = _header_index(ws)
        targets = []
        for header, attr in columns.items():
            col = idx.get(norm_header(header))
            if col is None:
                raise TemplateError(f"Column '{header}' not found on sheet '{name}' of the submission template.")
            targets.append((col, attr))

        # clear anything left below the header block (the template can carry stray sample values)
        for row in ws.iter_rows(min_row=SUBMISSION_FIRST_DATA_ROW):
            for c in row:
                c.value = None

        lines = groups[group]
        for i, line in enumerate(lines):
            r = SUBMISSION_FIRST_DATA_ROW + i
            for col, attr in targets:
                value = getattr(line, attr)
                if value is not None:
                    _put(ws, r, col, value)
        _border_table(ws, SUBMISSION_FIRST_DATA_ROW, len(lines))
        _black_text(ws, SUBMISSION_FIRST_DATA_ROW, len(lines))
        ws.freeze_panes = f"A{SUBMISSION_FIRST_DATA_ROW}"

    set_active_sheet(wb, wb.worksheets[0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
