"""Read a SPIR extraction workbook into a list of row dicts.

Expected layout (first sheet):
  row 1   column names  (S.NO, SPIR NO, TAG NO, ...)
  row 2   SAP field codes (NA, CDC_SPIRNUMBER, EQFNR, ...)   - skipped
  row 3   field lengths   (4, 25, 30, ...)                     - skipped
  row 4+  data
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import openpyxl

REQUIRED_COLUMNS = [
    "SPIR NO", "TAG NO", "EQPT MAKE", "EQPT MODEL", "EQPT SR NO", "EQPT QTY",
    "QUANTITY IDENTICAL PARTS FITTED", "POSITION NUMBER", "OLD MATERIAL NUMBER/SPF NUMBER",
    "DESCRIPTION OF PARTS", "NEW DESCRIPTION OF PARTS", "MANUFACTURER PART NUMBER",
    "SUPPLIER/ OCM NAME", "CURRENCY", "UNIT PRICE (QAR)", "DELIVERY TIME IN WEEKS",
    "MIN MAX STOCK LVLS QTY", "UNIT OF MEASURE", "SAP NUMBER", "SPIR TYPE", "VENDOR COUNTRY",
]


class InputFileError(ValueError):
    """The uploaded file is not a readable SPIR extraction."""


def norm_header(text: object) -> str:
    """Compare headers ignoring case, spaces and punctuation."""
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def clean(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


@dataclass
class InputRow:
    excel_row: int
    values: dict[str, str | None] = field(default_factory=dict)

    def get(self, column: str) -> str | None:
        return self.values.get(column)


def _is_meta_row(values: dict[str, str | None]) -> bool:
    """Row 2 (SAP field codes) and row 3 (field lengths) of the extraction."""
    spir = (values.get("SPIR NO") or "").upper()
    tag = values.get("TAG NO") or ""
    return spir in {"CDC_SPIRNUMBER", "NA"} or spir.isdigit() or tag.upper() == "EQFNR" or tag.isdigit()


def read_input(content: bytes) -> list[InputRow]:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise InputFileError("The file could not be opened as an Excel (.xlsx) workbook.") from exc

    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    try:
        header = next(rows)
    except StopIteration as exc:
        raise InputFileError("The input sheet is empty.") from exc

    wanted = {norm_header(c): c for c in REQUIRED_COLUMNS}
    index: dict[str, int] = {}
    for i, h in enumerate(header):
        key = norm_header(h)
        if key in wanted and wanted[key] not in index:
            index[wanted[key]] = i

    missing = [c for c in REQUIRED_COLUMNS if c not in index]
    if missing:
        raise InputFileError("Missing columns in the input file: " + ", ".join(missing))

    result: list[InputRow] = []
    for excel_row, raw in enumerate(rows, start=2):
        values = {col: clean(raw[i]) if i < len(raw) else None for col, i in index.items()}
        if not any(values.values()) or _is_meta_row(values):
            continue
        result.append(InputRow(excel_row=excel_row, values=values))
    wb.close()

    if not result:
        raise InputFileError("No data rows were found in the input file.")
    return result
