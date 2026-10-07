"""Business logic: SPIR extraction rows -> BOM WORKING TEMPLATE lines.

Implements docs/logic/*.txt. Pure python - no database or Excel code here, so it is easy to test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .input_reader import InputRow

DUKHAN = "DUKHAN"
OTHER = "OTHER"

DESC_MAX = 40
OLD_MAT_MAX = 18
MFR_NAME_MAX = 30
MFR_NAME_LABEL = "Manufacture name : "
ADD_INFO_SEPARATOR = " | "


class NumberAllocator(Protocol):
    """Hands out Material Temp Numbers. The same key always returns the same number."""

    def equipment(self, key: str) -> int: ...
    def spare(self, key: str) -> int: ...


# --------------------------------------------------------------------------- helpers
def code_part(value: str | None) -> str | None:
    """'NO - NUMBERS' -> 'NO', 'QAR - QATAR RIYAL' -> 'QAR'."""
    if not value:
        return None
    return value.split(" - ")[0].strip() or None


def split_spir(value: str | None) -> tuple[str | None, str | None]:
    """'VEN-4391-M3TY-2-43-0003-REV-A' -> ('VEN-4391-M3TY-2-43-0003', 'A')."""
    if not value:
        return None, None
    m = re.match(r"^(.*?)[-_\s]*REV[-_.\s]*([A-Z0-9]+)\s*$", value.strip(), re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).upper()
    return value.strip(), None


def fit_words(value: str | None, limit: int) -> str | None:
    """Keep as many whole words as fit in `limit` characters (spaces counted); never split a word.

    'EMERSON PROCESS AUTOMATION, QATAR' (30) -> 'EMERSON PROCESS AUTOMATION'.
    Punctuation left dangling at the cut (',', '-', '&', ...) is dropped. A value that already fits is
    returned unchanged. A single first word longer than the limit cannot be kept whole, so it is cut at
    the limit - the length rule wins.
    """
    if value is None or len(value) <= limit:
        return value
    kept = ""
    for word in value.split():
        candidate = f"{kept} {word}" if kept else word
        if len(candidate) > limit:
            break
        kept = candidate
    if not kept:
        return value.strip()[:limit].rstrip()
    return kept.rstrip(" ,;:-/&(") or kept


def to_number(value: str | None) -> int | float | str | None:
    if value is None:
        return None
    try:
        f = float(value.replace(",", ""))
    except ValueError:
        return value
    return int(f) if f.is_integer() else round(f, 2)


def to_int_if_digits(value: str | None) -> int | str | None:
    if value is None:
        return None
    return int(value) if value.isdigit() else value


def split_min_max(value: str | None) -> tuple[int | float | str | None, int | float | str | None]:
    """MIN MAX STOCK LVLS QTY rule.

    * a single-digit value ("0", "1")         -> REORDER POINT (MIN)
    * a multi-digit value ("12", "120")       -> MAXIMUM STOCK LEVEL (MAX)
    * two values ("1/3", "1-3", "1,3", "1 3") -> MIN = first, MAX = second
    """
    if not value:
        return None, None
    parts = re.findall(r"\d+(?:\.\d+)?", value)
    if len(parts) >= 2:
        return to_number(parts[0]), to_number(parts[1])
    if len(parts) == 1:
        digits = parts[0].split(".")[0]
        return (to_number(parts[0]), None) if len(digits) <= 1 else (None, to_number(parts[0]))
    return None, None


# --------------------------------------------------------------------------- output model
@dataclass
class BomLine:
    serial: int
    category: str                       # B = equipment, L = spare
    tag: str
    sap_material_number: int | str | None
    temp_number: int | str
    old_material_number: str | None
    description: str | None
    planning_plant: str | None
    uom: str | None
    mfr_part_number: str | None
    mfr_name: str | None
    equipment_indicator: str            # YES / NO
    bom_header_number: int | str
    quantity: int | float | str | None
    position_number: str | None
    spir_number: str | None
    delivery_weeks: int | float | str | None
    country_code: str | None
    price: int | float | str | None
    add_information: str | None         # full manufacturer part number when it was cut to fit
    min_qty: int | float | str | None
    max_qty: int | float | str | None
    country_name: str | None
    currency: str | None
    input_row: int
    mfr_name_full: str | None = None    # full manufacturer name when it was shortened to fit

    @property
    def add_information_text(self) -> str | None:
        """CDC_ADD INFORMATION cell: the full part number and/or 'Manufacture name : <full name>'."""
        parts = [self.add_information] if self.add_information else []
        if self.mfr_name_full:
            parts.append(f"{MFR_NAME_LABEL}{self.mfr_name_full}")
        return ADD_INFO_SEPARATOR.join(parts) or None


def part_number_from_add_information(text: str | None) -> str | None:
    """Inverse of BomLine.add_information_text: the full part number only (manufacturer name note removed)."""
    if not text:
        return None
    if text.startswith(MFR_NAME_LABEL):
        return None
    return text.split(ADD_INFO_SEPARATOR + MFR_NAME_LABEL)[0] or None


@dataclass
class TagLine:
    tag: str
    submt: int | str
    spir_no: str | None
    rev: str | None
    herst: str | None
    typbz: str | None
    mapar: str | None
    serge: str | None
    spir_type: str | None


@dataclass
class Warning_:
    code: str
    message: str
    lines: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "lines": self.lines}


@dataclass
class BomResult:
    lines: list[BomLine]
    tags: list[TagLine]
    warnings: list[Warning_]
    spir_numbers: list[str]

    @property
    def equipment_count(self) -> int:
        return sum(1 for line in self.lines if line.category == "B")

    @property
    def spare_count(self) -> int:
        return sum(1 for line in self.lines if line.category == "L")


# --------------------------------------------------------------------------- builder
def _is_equipment(row: InputRow) -> bool:
    return bool(row.get("EQPT QTY")) and not row.get("QUANTITY IDENTICAL PARTS FITTED")


def normalize_part_number(value: str) -> str:
    """'1sbl  137001r1110 ' -> '1SBL 137001R1110' (case and extra spaces do not make a new part)."""
    return " ".join(value.split()).upper()


def _spare_key(row: InputRow) -> str:
    """One manufacturer part number = one temp number; SAP / SPF / description only when there is no part number."""
    pn = row.get("MANUFACTURER PART NUMBER")
    if pn and pn.strip():
        return f"PN:{normalize_part_number(pn)}"
    sap = row.get("SAP NUMBER")
    if sap:
        return f"SAP:{sap}"
    spf = row.get("OLD MATERIAL NUMBER/SPF NUMBER")
    if spf:
        return f"SPF:{spf.upper()}"
    return "DESC:" + "|".join(
        (row.get(c) or "").upper()
        for c in ("SUPPLIER/ OCM NAME", "MANUFACTURER PART NUMBER", "NEW DESCRIPTION OF PARTS", "DESCRIPTION OF PARTS")
    )[:290]


def build_bom(
    rows: list[InputRow],
    plant_type: str,
    planning_plant: str | None,
    allocator: NumberAllocator,
    country_codes: dict[str, str],
    mfr_pn_max: int = 35,
) -> BomResult:
    plant_type = plant_type.upper()
    if plant_type not in (DUKHAN, OTHER):
        raise ValueError(f"Unknown plant type {plant_type!r}")

    warn: dict[str, Warning_] = {}

    def add_warning(code: str, message: str, line: int | None = None) -> None:
        w = warn.setdefault(code, Warning_(code, message))
        if line is not None and line not in w.lines:
            w.lines.append(line)

    # 1. group rows: one equipment per TAG NO (even when the tag repeats in several input sheets),
    #    its spares listed underneath in input order.
    tag_order: list[str] = []
    header: dict[str, InputRow] = {}
    spares: dict[str, list[InputRow]] = {}
    for row in rows:
        tag = row.get("TAG NO")
        if not tag:
            add_warning("NO_TAG", "Input rows without a TAG NO were skipped (see input Excel row numbers).", row.excel_row)
            continue
        key = tag.upper()
        if key not in spares:
            tag_order.append(key)
            spares[key] = []
        if _is_equipment(row):
            header.setdefault(key, row)
        else:
            spares[key].append(row)

    # 2. build lines
    lines: list[BomLine] = []
    tags: list[TagLine] = []
    spir_numbers: list[str] = []

    def country(row: InputRow, serial: int) -> tuple[str | None, str | None]:
        name = row.get("VENDOR COUNTRY")
        if not name:
            return None, None
        code = country_codes.get(name.strip().upper())
        if not code:
            add_warning("COUNTRY_NOT_FOUND",
                        f"Vendor country not found in the country reference (code left empty): {name}", serial)
        return code, name

    def mfr_name(row: InputRow, serial: int) -> tuple[str | None, str | None]:
        """(name for MANUFACTURER NAME, full name for CDC_ADD INFORMATION - only when it was shortened)."""
        name = row.get("SUPPLIER/ OCM NAME")
        if not name or len(name) <= MFR_NAME_MAX:
            return name, None
        add_warning("MFR_NAME_TOO_LONG",
                    f"Manufacturer name longer than {MFR_NAME_MAX} characters - shortened to whole words, "
                    "full name kept in CDC_ADD INFORMATION.", serial)
        return fit_words(name, MFR_NAME_MAX), name

    for key in tag_order:
        h = header.get(key)
        if h is None:
            h = spares[key][0]
            add_warning("NO_EQUIPMENT_ROW",
                        "Tag(s) with spares but no equipment header row - equipment line built from the first spare row.",
                        h.excel_row)
        tag = h.get("TAG NO") or key
        eq_sap = h.get("SAP NUMBER") if key in header else None
        if plant_type == OTHER and eq_sap:
            eq_temp: int | str = to_int_if_digits(eq_sap)  # type: ignore[assignment]
        else:
            eq_temp = allocator.equipment(f"TAG:{key}")
        spir_base, rev = split_spir(h.get("SPIR NO"))
        if spir_base and spir_base not in spir_numbers:
            spir_numbers.append(spir_base)

        # --- equipment line
        # Equipment-level columns always come from the row; part-level columns only when a real
        # equipment header row exists (not when the line was synthesised from a spare row).
        has_header = key in header

        def eq(column: str) -> str | None:
            return h.get(column) if has_header else None

        serial = len(lines) + 1
        code, cname = country(h, serial)
        eq_mname, eq_mname_full = mfr_name(h, serial)
        min_q, max_q = split_min_max(eq("MIN MAX STOCK LVLS QTY"))
        lines.append(BomLine(
            serial=serial, category="B", tag=tag,
            sap_material_number=to_int_if_digits(eq("SAP NUMBER")),
            temp_number=eq_temp,
            old_material_number=eq("OLD MATERIAL NUMBER/SPF NUMBER"),
            description=eq("NEW DESCRIPTION OF PARTS") or eq("DESCRIPTION OF PARTS"),
            planning_plant=planning_plant,
            uom=code_part(eq("UNIT OF MEASURE")),
            mfr_part_number=eq("MANUFACTURER PART NUMBER"), mfr_name=eq_mname,
            equipment_indicator="YES", bom_header_number=eq_temp,
            quantity=to_number(eq("EQPT QTY")),
            position_number=eq("POSITION NUMBER"),
            spir_number=spir_base,
            delivery_weeks=to_number(eq("DELIVERY TIME IN WEEKS")),
            country_code=code, price=to_number(eq("UNIT PRICE (QAR)")),
            add_information=None, min_qty=min_q, max_qty=max_q, country_name=cname,
            currency=code_part(eq("CURRENCY")),
            input_row=h.excel_row, mfr_name_full=eq_mname_full,
        ))
        tags.append(TagLine(
            tag=tag, submt=eq_temp, spir_no=spir_base, rev=rev,
            herst=h.get("SUPPLIER/ OCM NAME"), typbz=h.get("EQPT MODEL"),
            mapar=eq("MANUFACTURER PART NUMBER"),
            serge=h.get("EQPT SR NO"), spir_type=h.get("SPIR TYPE"),
        ))

        # --- spare lines
        for s in spares[key]:
            serial = len(lines) + 1
            sap = s.get("SAP NUMBER")
            if plant_type == OTHER and sap:
                temp: int | str = to_int_if_digits(sap)  # type: ignore[assignment]
            else:
                temp = allocator.spare(_spare_key(s))
                if plant_type == OTHER:
                    add_warning("NO_SAP_NUMBER", "Spares without SAP NUMBER were given a new 5xxxxx temp number.", serial)

            pn = s.get("MANUFACTURER PART NUMBER")
            add_info = None
            if pn and len(pn) > mfr_pn_max:
                add_info, pn = pn, pn[:mfr_pn_max]
                add_warning("MFR_PN_TOO_LONG",
                            f"Manufacturer part number longer than {mfr_pn_max} characters - full value moved to CDC_ADD INFORMATION.",
                            serial)

            desc = s.get("NEW DESCRIPTION OF PARTS") or s.get("DESCRIPTION OF PARTS")
            if desc and len(desc) > DESC_MAX:
                add_warning("DESC_TOO_LONG", f"Material description longer than {DESC_MAX} characters.", serial)
            old = s.get("OLD MATERIAL NUMBER/SPF NUMBER")
            if old and len(old) > OLD_MAT_MAX:
                add_warning("OLD_MAT_TOO_LONG", f"Old material / SPF number longer than {OLD_MAT_MAX} characters.", serial)
            mname, mname_full = mfr_name(s, serial)
            qty = to_number(s.get("QUANTITY IDENTICAL PARTS FITTED"))
            if qty is None:
                add_warning("NO_QUANTITY", "Spare lines without QUANTITY IDENTICAL PARTS FITTED.", serial)

            s_spir, _ = split_spir(s.get("SPIR NO"))
            if s_spir and s_spir not in spir_numbers:
                spir_numbers.append(s_spir)
            code, cname = country(s, serial)
            min_q, max_q = split_min_max(s.get("MIN MAX STOCK LVLS QTY"))
            lines.append(BomLine(
                serial=serial, category="L", tag=tag,
                sap_material_number=to_int_if_digits(sap),
                temp_number=temp,
                old_material_number=old,
                description=desc,
                planning_plant=planning_plant,
                uom=code_part(s.get("UNIT OF MEASURE")),
                mfr_part_number=pn, mfr_name=mname,
                equipment_indicator="NO", bom_header_number=eq_temp,
                quantity=qty,
                position_number=s.get("POSITION NUMBER"),
                spir_number=s_spir,
                delivery_weeks=to_number(s.get("DELIVERY TIME IN WEEKS")),
                country_code=code, price=to_number(s.get("UNIT PRICE (QAR)")),
                add_information=add_info, min_qty=min_q, max_qty=max_q, country_name=cname,
                currency=code_part(s.get("CURRENCY")),
                input_row=s.excel_row, mfr_name_full=mname_full,
            ))

    if len(spir_numbers) > 1:
        add_warning("MULTIPLE_SPIR", "The input file contains more than one SPIR number: " + ", ".join(spir_numbers))

    return BomResult(lines=lines, tags=tags, warnings=list(warn.values()), spir_numbers=spir_numbers)


class InMemoryAllocator:
    """Allocator without a database (used by tests and the command line)."""

    def __init__(self, equipment_start: int = 40001, spare_start: int = 500001):
        self._next = {"EQUIPMENT": equipment_start, "SPARE": spare_start}
        self._known: dict[tuple[str, str], int] = {}

    def _get(self, kind: str, key: str) -> int:
        if (kind, key) not in self._known:
            self._known[(kind, key)] = self._next[kind]
            self._next[kind] += 1
        return self._known[(kind, key)]

    def equipment(self, key: str) -> int:
        return self._get("EQUIPMENT", key)

    def spare(self, key: str) -> int:
        return self._get("SPARE", key)
