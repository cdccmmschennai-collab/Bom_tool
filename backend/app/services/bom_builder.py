"""Business logic: SPIR extraction rows -> BOM WORKING TEMPLATE lines.

Implements docs/logic/*.txt. Pure python - no database or Excel code here, so it is easy to test.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Protocol

from .input_reader import InputRow

DUKHAN = "DUKHAN"
OTHER = "OTHER"

DESC_MAX = 40
OLD_MAT_MAX = 18
NON_STOCK_SAP_PREFIXES = ("3", "8")  # spare with such a SAP number -> MATERIAL TYPEVCATEGORY N
SAP_NUMBER_MIN = 1_000_000  # temp numbers have 5 / 6 digits (4xxxx, 5xxxxx); a longer number is a SAP number
EQUIPMENT_OLD_MAT_PREFIX = "QEQU-"  # equipment OLD MATERIAL NUMBER/SPF NUMBER = QEQU-<MATERIAL TEMP NUMBER>
EQUIPMENT_UOM = "EA"  # equipment BASE UNIT OF MEASURE is always EA (the input UNIT OF MEASURE is not used)
MFR_NAME_MAX = 30
MFR_NAME_LABEL = "Manufacture name : "
ADD_INFO_SEPARATOR = " | "

# equipment classes for the SUBMT rules (words of the equipment description, whole words, plural allowed)
VALVE, CABINET, OTHER_EQUIPMENT = "VALVE", "CABINET", "OTHER"
VALVE_WORDS = ("VALVE",)
NOT_MANUAL_VALVE_WORDS = ("CONTROL", "ACTUATED", "ACTUATOR", "SOLENOID", "MOTORISED", "MOTORIZED",
                          "MOV", "SDV", "ESDV", "PCV", "LCV", "FCV", "TCV")
CABINET_WORDS = ("CABINET", "PANEL", "ENCLOSURE", "CUBICLE", "SWITCHBOARD", "SWITCHGEAR", "MCC")
MESC_LABELLED_RE = re.compile(r"\bMESC\b\W*((?:\d[.\s-]?){9}\d?)\b", re.IGNORECASE)
MESC_DOTTED_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{2}\.\d{3}(?:\.\d)?)\b")
# 'P/N:', 'PN', 'PART NO.', 'PART NUMBER #' as whole words (so 'PN50' or 'SPN-12' are not labels), on normalised text
PART_NUMBER_LABEL_RE = re.compile(r"(?<![A-Z0-9])(?:P/N|PN|PART NUMBER|PART NO)(?![A-Z0-9])\s*[:#.\-]?\s*")
# '<model name>-<LOCATION>' on normalised text: base ending in a letter, then '-' and one word of 4+ letters
MODEL_LOCATION_SUFFIX_RE = re.compile(r"^(.*[A-Z])\s*[-–]\s*[A-Z]{4,}$")


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
    spir_number_full: str | None = None  # SPIR NO as in the input, revision kept - working and submission templates
    review: list[str] = field(default_factory=list)  # why the line needs a manual check (VERIFICATION sheet)

    @property
    def type_category(self) -> str:
        """MATERIAL TYPEVCATEGORY as written to the templates and the material master: N for a spare whose
        SAP number starts with 3 or 8 (every plant), else the category (B / L). `category` itself stays B / L."""
        sap = self.sap_material_number
        if not sap and isinstance(self.temp_number, int) and self.temp_number >= SAP_NUMBER_MIN:
            sap = self.temp_number  # no SAP NUMBER in the row, but the number reused from the master is one
        sap = str(sap or "").strip()
        return "N" if self.category == "L" and sap.startswith(NON_STOCK_SAP_PREFIXES) else self.category

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


def _part_identity(temp: int | str, part_number: str | None) -> tuple:
    """(temp number, normalised full part number or None): one spare line of a BOM header."""
    pn = normalize_part_number(part_number) if part_number else ""
    return temp, pn or None


def spare_identity(line: BomLine) -> tuple:
    """What makes a spare one line under its BOM header: the temp number (= the SAP NUMBER when there is one) and
    the full manufacturer part number. Same SAP + same part number = one line (quantities added under one tag);
    same SAP + another part number = its own line."""
    return _part_identity(line.temp_number, line.add_information or line.mfr_part_number)


def add_quantities(a: int | float | str | None, b: int | float | str | None) -> int | float | str | None:
    """a + b for numbers (blank counts as nothing); a text quantity cannot be added - `a` is kept."""
    if a is None:
        return b
    if b is None:
        return a
    if isinstance(a, str) or isinstance(b, str):
        return a
    total = a + b
    return int(total) if float(total).is_integer() else round(total, 2)


def _description(row: InputRow) -> str:
    return (row.get("NEW DESCRIPTION OF PARTS") or row.get("DESCRIPTION OF PARTS") or "").upper()


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(w)}S?\b", text) for w in words)


def equipment_class(row: InputRow) -> str:
    """VALVE (manual valve), CABINET or OTHER, from the words of the equipment description."""
    desc = _description(row)
    if _has_word(desc, VALVE_WORDS) and not _has_word(desc, NOT_MANUAL_VALVE_WORDS):
        return VALVE
    if _has_word(desc, CABINET_WORDS):
        return CABINET
    return OTHER_EQUIPMENT


def mesc_number(text: str | None) -> str | None:
    """MESC number in a description, digits only: 'GATE VALVE MESC 74.10.21.104.1' -> '7410211041'.
    A number after the word MESC may be written with or without separators; without the word, only the
    dotted form (74.10.21.104 / 74.10.21.104.1) is taken, so other numbers in the text are not mistaken for one."""
    if not text:
        return None
    m = MESC_LABELLED_RE.search(text) or MESC_DOTTED_RE.search(text)
    return re.sub(r"\D", "", m.group(1)) if m else None


def base_model(value: str) -> str:
    """EQPT MODEL for equipment numbering: normalised, without a location suffix, so one model installed at
    several locations is one model: "AB' GLM RIO PANEL-KHATIYA" / "-FAHAHIL" -> "AB' GLM RIO PANEL".
    A suffix counts only when it is one word of 4+ letters after a model name with a space that ends in a word;
    model codes keep their dashes ("NFF-SPH-4W", "BRK 703-704", "ROSEMOUNT 3051-HART").
    Used for the numbering keys only - the model written to the templates is never changed."""
    text = normalize_part_number(value)
    m = MODEL_LOCATION_SUFFIX_RE.match(text)
    return m.group(1) if m and " " in m.group(1) else text


def _make_model_key(row: InputRow, base: bool = False) -> str | None:
    """MM:<make>|<model>; base=True (equipment numbering) uses the model without a location suffix."""
    make, model = row.get("EQPT MAKE"), row.get("EQPT MODEL")
    if make and make.strip() and model and model.strip():
        return f"MM:{normalize_part_number(make)}|{base_model(model) if base else normalize_part_number(model)}"
    return None


@dataclass
class _Block:
    """One equipment of a tag and its spares. number_key is the tag, plus #2, #3.. for later blocks of the same tag,
    so blocks numbered by tag do not share a number."""
    tag_key: str
    number_key: str
    header: InputRow | None = None
    spares: list[InputRow] = field(default_factory=list)


def _equipment_identity(row: InputRow) -> str:
    """What tells one equipment from another under a repeated tag: make + model, else part number, else description."""
    pn = row.get("MANUFACTURER PART NUMBER")
    return _make_model_key(row) or (f"PN:{normalize_part_number(pn)}" if pn and pn.strip() else
                                    "DESC:" + normalize_part_number(_description(row)))


def _core_part_number(value: str) -> str:
    """Normalised part number, only the part after a part-number label when there is one:
    'DRAGER PAS LITE-P/N: 3357774' -> '3357774'. Used to tell whether a spare is the equipment itself;
    the part number written to the templates and the numbering keys keep the full value."""
    text = normalize_part_number(value)
    labels = list(PART_NUMBER_LABEL_RE.finditer(text))
    rest = text[labels[-1].end():].strip() if labels else ""
    return rest or text


def _same_item_make(header: InputRow, spare_rows: list[InputRow]) -> str | None:
    """SUPPLIER/ OCM NAME of the first spare with the equipment's own part number (the spare is the equipment itself)."""
    pn = header.get("MANUFACTURER PART NUMBER")
    if not pn or not pn.strip():
        return None
    pn = _core_part_number(pn)
    for s in spare_rows:
        spare_pn = s.get("MANUFACTURER PART NUMBER")
        if spare_pn and spare_pn.strip() and _core_part_number(spare_pn) == pn:
            name = s.get("SUPPLIER/ OCM NAME")
            if name and name.strip():
                return name
    return None


def _equipment_part_numbers(blocks: list[_Block]) -> dict[str, list[_Block]]:
    """Core part number -> the equipment blocks (with an equipment row) that have it, in input order."""
    out: dict[str, list[_Block]] = {}
    for block in blocks:
        pn = block.header.get("MANUFACTURER PART NUMBER") if block.header else None
        if pn and pn.strip():
            out.setdefault(_core_part_number(pn), []).append(block)
    return out


def _part_number_review(spare: InputRow, block: _Block, equipment_pns: dict[str, list[_Block]]) -> list[str]:
    """VERIFICATION reason for a spare whose part number is the part number of an equipment in the file:
    its own equipment (the spare is probably the equipment itself) or only other equipment (the rows disagree).
    Case, extra spaces and a 'P/N:' label do not count. No match -> no reason."""
    pn = spare.get("MANUFACTURER PART NUMBER")
    if not pn or not pn.strip():
        return []
    matches = equipment_pns.get(_core_part_number(pn), [])
    if not matches:
        return []
    own_tag = spare.get("TAG NO")
    if block in matches:
        return [f"Same part number as its equipment (tag {own_tag}) - check whether this is the equipment itself, "
                "not a spare."]
    tags = list(dict.fromkeys(b.header.get("TAG NO") for b in matches if b.header))
    own_pn = block.header.get("MANUFACTURER PART NUMBER") if block.header else None
    return [f"Part number {pn} is the equipment part number of tag(s) {', '.join(tags)}, but its own equipment "
            f"(tag {own_tag}) has {own_pn or 'no part number'} - check which is right."]


def _installed_with_quantities(spare_rows: list[InputRow]) -> list[tuple[str, str | None]]:
    """(spare key, quantity) per installed spare, sorted. A spare repeated under the tag keeps its first quantity,
    as in the templates; the quantity is normalised ("2" = "2.0"), blank stays None."""
    first: dict[str, str | None] = {}
    for s in spare_rows:
        qty = to_number(s.get("QUANTITY IDENTICAL PARTS FITTED"))
        first.setdefault(_spare_key(s), None if qty is None else str(qty).strip().upper() or None)
    return sorted(first.items(), key=lambda kv: (kv[0], kv[1] or ""))


def _equipment_key(row: InputRow, tag_key: str, has_header: bool, spare_rows: list[InputRow],
                   cabinet_quantities: bool = True) -> str:
    """SUBMT rules (a SAP NUMBER is used before this is called):
    * manual valve  -> one temp number per MESC number in the description (else as other equipment)
    * cabinet       -> one temp number per make + model + installed spares with their quantities: same parts in
                       other quantities = another cabinet (key prefix CABINETQ:). cabinet_quantities=False
                       (setting CABINET_COMPARE_QUANTITIES=false) is the old rule: quantities are not compared
                       (key prefix CABINET:, the templates keep the first tag's quantities). The two modes never
                       share numbers. Description + supplier stand in for a missing make / model.
    * other         -> one temp number per make + model; without both, per manufacturer part number
    By tag when none of these can be told, or when the line was built from a spare row."""
    if not has_header:
        return f"TAG:{tag_key}"
    kind = equipment_class(row)
    if kind == VALVE:
        mesc = mesc_number(_description(row))
        if mesc:
            return f"MESC:{mesc}"
    if kind == CABINET:
        installed: list = (_installed_with_quantities(spare_rows) if cabinet_quantities
                           else sorted({_spare_key(s) for s in spare_rows}))
        make, model = normalize_part_number(row.get("EQPT MAKE") or ""), base_model(row.get("EQPT MODEL") or "")
        if make and model:
            identity: tuple[str, str] = (make, model)
        elif installed:
            identity = (_description(row), (row.get("SUPPLIER/ OCM NAME") or "").upper())
        else:
            return f"TAG:{tag_key}"
        signature = repr((identity, installed))
        prefix = "CABINETQ:" if cabinet_quantities else "CABINET:"
        return prefix + hashlib.sha1(signature.encode()).hexdigest()
    pn = row.get("MANUFACTURER PART NUMBER")
    return _make_model_key(row, base=True) or (f"PN:{normalize_part_number(pn)}" if pn and pn.strip()
                                               else f"TAG:{tag_key}")


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
    cabinet_quantities: bool = True,
) -> BomResult:
    plant_type = plant_type.upper()
    if plant_type not in (DUKHAN, OTHER):
        raise ValueError(f"Unknown plant type {plant_type!r}")

    warn: dict[str, Warning_] = {}

    def add_warning(code: str, message: str, line: int | None = None) -> None:
        w = warn.setdefault(code, Warning_(code, message))
        if line is not None and line not in w.lines:
            w.lines.append(line)

    # 1. group rows into equipment blocks: one per TAG NO and equipment, its spares listed underneath in input order.
    #    A spare belongs to the nearest equipment row above it with its tag. The tag repeated with the same
    #    equipment (e.g. in several input sheets) stays one block; with another equipment it opens a new block.
    blocks: list[_Block] = []
    current: dict[str, _Block] = {}  # tag -> its last block
    for row in rows:
        tag = row.get("TAG NO")
        if not tag:
            add_warning("NO_TAG", "Input rows without a TAG NO were skipped (see input Excel row numbers).", row.excel_row)
            continue
        tag_key = tag.upper()
        block = current.get(tag_key)
        if _is_equipment(row) and block is not None and block.header is not None \
                and _equipment_identity(row) != _equipment_identity(block.header):
            add_warning("TAG_REPEATED_OTHER_EQUIPMENT",
                        "Tag(s) repeated with another equipment - listed as a separate equipment with its own BOM "
                        "(see input Excel row numbers).", row.excel_row)
            block = None
        if block is None:
            index = sum(1 for b in blocks if b.tag_key == tag_key)
            block = current[tag_key] = _Block(tag_key, f"{tag_key}#{index + 1}" if index else tag_key)
            blocks.append(block)
        if _is_equipment(row):
            if block.header is None:
                block.header = row
        else:
            block.spares.append(row)

    # 2. build lines
    lines: list[BomLine] = []
    tags: list[TagLine] = []
    spir_numbers: list[str] = []
    header_spares: dict[int | str, dict] = {}  # BOM header -> spare temp -> quantity of its first line
    equipment_pns = _equipment_part_numbers(blocks)  # for the VERIFICATION sheet only

    def country(row: InputRow, serial: int) -> tuple[str | None, str | None]:
        name = row.get("VENDOR COUNTRY")
        if not name:
            return None, None
        code = country_codes.get(name.strip().upper())
        if not code:
            add_warning("COUNTRY_NOT_FOUND",
                        f"Vendor country not found in the country reference (code left empty): {name}", serial)
        return code, name

    def mfr_name(name: str | None, serial: int) -> tuple[str | None, str | None]:
        """(name for MANUFACTURER NAME, full name for CDC_ADD INFORMATION - only when it was shortened)."""
        if not name or len(name) <= MFR_NAME_MAX:
            return name, None
        add_warning("MFR_NAME_TOO_LONG",
                    f"Manufacturer name longer than {MFR_NAME_MAX} characters - shortened to whole words, "
                    "full name kept in CDC_ADD INFORMATION.", serial)
        return fit_words(name, MFR_NAME_MAX), name

    for block in blocks:
        key = block.tag_key
        has_header = block.header is not None
        h = block.header or block.spares[0]
        if not has_header:
            add_warning("NO_EQUIPMENT_ROW",
                        "Tag(s) with spares but no equipment header row - equipment line built from the first spare row.",
                        h.excel_row)
        tag = h.get("TAG NO") or key
        eq_sap = h.get("SAP NUMBER") if has_header else None
        if eq_sap:  # a SAP NUMBER is the MATERIAL TEMP NUMBER in every plant (Dukhan and others)
            eq_temp: int | str = to_int_if_digits(eq_sap)  # type: ignore[assignment]
        else:
            eq_key = _equipment_key(h, block.number_key, has_header, block.spares, cabinet_quantities)
            eq_temp = allocator.equipment(eq_key)
            if has_header and equipment_class(h) == VALVE and not eq_key.startswith("MESC:"):
                add_warning("VALVE_NO_MESC", "Manual valve(s) without a MESC number in the description - "
                            "numbered by make and model (or part number / tag) instead.", len(lines) + 1)
        spir_base, rev = split_spir(h.get("SPIR NO"))
        if spir_base and spir_base not in spir_numbers:
            spir_numbers.append(spir_base)

        # --- equipment line
        # Equipment-level columns always come from the row; part-level columns only when a real
        # equipment header row exists (not when the line was synthesised from a spare row).

        def eq(column: str) -> str | None:
            return h.get(column) if has_header else None

        serial = len(lines) + 1
        code, cname = country(h, serial)
        # equipment manufacturer = EQPT MAKE of the equipment row (EQPT QTY filled); empty when the line was
        # built from a spare row. HERST on the tag sheet always gets EQPT MAKE; spares use SUPPLIER/ OCM NAME.
        # When a spare is the equipment itself (same part number), its SUPPLIER/ OCM NAME is used instead.
        eq_make = (_same_item_make(h, block.spares) if has_header else None) or eq("EQPT MAKE")
        eq_mname, eq_mname_full = mfr_name(eq_make, serial)
        min_q, max_q = split_min_max(eq("MIN MAX STOCK LVLS QTY"))
        lines.append(BomLine(
            serial=serial, category="B", tag=tag,
            sap_material_number=to_int_if_digits(eq("SAP NUMBER")),
            temp_number=eq_temp,
            old_material_number=f"{EQUIPMENT_OLD_MAT_PREFIX}{eq_temp}",
            description=eq("NEW DESCRIPTION OF PARTS") or eq("DESCRIPTION OF PARTS"),
            planning_plant=planning_plant,
            uom=EQUIPMENT_UOM,
            mfr_part_number=eq("MANUFACTURER PART NUMBER"), mfr_name=eq_mname,
            equipment_indicator="YES", bom_header_number=eq_temp,
            quantity=to_number(eq("EQPT QTY")),
            position_number=eq("POSITION NUMBER"),
            spir_number=spir_base,
            delivery_weeks=to_number(eq("DELIVERY TIME IN WEEKS")),
            country_code=code, price=to_number(eq("UNIT PRICE (QAR)")),
            add_information=None, min_qty=min_q, max_qty=max_q, country_name=cname,
            currency=code_part(eq("CURRENCY")),
            input_row=h.excel_row, mfr_name_full=eq_mname_full, spir_number_full=h.get("SPIR NO"),
        ))
        tags.append(TagLine(
            tag=tag, submt=eq_temp, spir_no=spir_base, rev=rev,
            herst=eq("EQPT MAKE"), typbz=h.get("EQPT MODEL"),  # full name, never shortened
            mapar=eq("MANUFACTURER PART NUMBER"),
            serge=h.get("EQPT SR NO"), spir_type=h.get("SPIR TYPE"),
        ))

        # --- spare lines
        listed = header_spares.setdefault(eq_temp, {})
        in_tag: dict[tuple, int | float | str | None] = {}  # spare identity -> its quantities added up under this tag
        rows_of: dict[tuple, list[int]] = {}  # spare identity -> its input rows under this tag
        for s in block.spares:
            serial = len(lines) + 1
            sap = s.get("SAP NUMBER")
            if sap:  # a SAP NUMBER is the MATERIAL TEMP NUMBER in every plant (Dukhan and others)
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
            mname, mname_full = mfr_name(s.get("SUPPLIER/ OCM NAME"), serial)
            qty = to_number(s.get("QUANTITY IDENTICAL PARTS FITTED"))
            if qty is None:
                add_warning("NO_QUANTITY", "Spare lines without QUANTITY IDENTICAL PARTS FITTED.", serial)
            # the templates list each spare (SAP / temp number + part number) once per BOM header: repeats under
            # one tag are added up, another tag of the same header keeps the first tag's total
            ident = _part_identity(temp, s.get("MANUFACTURER PART NUMBER"))
            if ident in in_tag:
                add_warning("REPEATED_SPARE",
                            "Spare(s) repeated under the same tag (same SAP / part number) - quantities added into "
                            "one line in the templates (see input Excel row numbers).", s.excel_row)
                if isinstance(qty, str) or isinstance(in_tag[ident], str):
                    add_warning("QUANTITY_NOT_ADDED",
                                "Repeated spare(s) with a quantity that is not a number - not added, the templates "
                                "keep the first quantity (see input Excel row numbers).", s.excel_row)
                in_tag[ident] = add_quantities(in_tag[ident], qty)
            else:
                in_tag[ident] = qty
            rows_of.setdefault(ident, []).append(s.excel_row)

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
                input_row=s.excel_row, mfr_name_full=mname_full, spir_number_full=s.get("SPIR NO"),
                review=_part_number_review(s, block, equipment_pns),
            ))

        differs = [r for ident, total in in_tag.items() if listed.setdefault(ident, total) != total
                   for r in rows_of[ident]]
        for r in sorted(differs):
            add_warning("QUANTITY_DIFFERS",
                        "Spare(s) with another quantity (added up under the tag) than under the first tag of the same "
                        "BOM header - the templates keep the first tag's quantity (see input Excel row numbers).", r)

    for line in lines:
        if line.review:
            add_warning("VERIFY", "Line(s) the tool is not sure about - listed on the VERIFICATION sheet of the "
                        "working template for a manual check.", line.serial)

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
