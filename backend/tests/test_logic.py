"""Business-logic tests (no database needed)."""
import io

import openpyxl
import pytest

from app.config import get_settings
from app.services.bom_builder import (DUKHAN, OTHER, InMemoryAllocator, build_bom, code_part,
                                      split_min_max, split_spir)
from app.services.excel_writer import write_workbook
from app.services.input_reader import InputFileError, read_input

COUNTRIES = {"QATAR": "QA"}


def build(sample_bytes, plant_type, plant="DK01"):
    return build_bom(read_input(sample_bytes), plant_type, plant, InMemoryAllocator(), COUNTRIES)


def test_helpers():
    assert split_spir("VEN-4391-M3TY-2-43-0003-REV-A") == ("VEN-4391-M3TY-2-43-0003", "A")
    assert split_spir("VEN-4391-M3TY-2-43-0003") == ("VEN-4391-M3TY-2-43-0003", None)
    assert code_part("NO - NUMBERS") == "NO"
    assert code_part("QAR - QATAR RIYAL") == "QAR"
    assert split_min_max("1") == (1, None)
    assert split_min_max("0") == (0, None)
    assert split_min_max("12") == (None, 12)
    assert split_min_max("120") == (None, 120)
    assert split_min_max("1/3") == (1, 3)


def test_reader_skips_meta_rows(sample_bytes):
    rows = read_input(sample_bytes)
    assert len(rows) == 78
    assert rows[0].get("TAG NO") == "34-QD-23"


def test_reader_rejects_wrong_file():
    wb = openpyxl.Workbook()
    wb.active.append(["A", "B"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(InputFileError, match="Missing columns"):
        read_input(buf.getvalue())


def test_dukhan_lines(sample_bytes):
    res = build(sample_bytes, DUKHAN)
    assert (res.equipment_count, res.spare_count, len(res.lines)) == (4, 70, 74)
    eq = res.lines[0]
    assert (eq.category, eq.equipment_indicator, eq.temp_number, eq.bom_header_number) == ("B", "YES", 40001, 40001)
    assert eq.description == "LV SWITCHGEAR" and eq.quantity == 1 and eq.planning_plant == "DK01"
    sp = res.lines[1]
    assert sp.category == "L" and sp.equipment_indicator == "NO"
    assert sp.sap_material_number == 10231307 and sp.temp_number == 10231307  # SAP number used in Dukhan too
    assert sp.bom_header_number == 40001 and sp.quantity == 4 and sp.position_number == "0010"
    assert sp.spir_number == "VEN-4391-M3TY-2-43-0003"
    assert sp.uom == "NO" and sp.currency == "QAR" and sp.country_code == "QA" and sp.country_name == "QATAR"
    # every equipment line is EA, whatever its input UNIT OF MEASURE; spares keep their own
    assert {line.uom for line in res.lines if line.category == "B"} == {"EA"}
    assert sp.price == 75.3 and sp.delivery_weeks == 20 and sp.min_qty == 1 and sp.max_qty is None
    # same material under several tags keeps one temp number
    by_sap = {}
    for line in res.lines:
        if line.category == "L":
            by_sap.setdefault(line.sap_material_number, set()).add(line.temp_number)
    assert all(len(v) == 1 for v in by_sap.values())
    assert len(by_sap) == 62
    # tags repeated over several input sheets are merged into one equipment
    assert [t.tag for t in res.tags] == ["34-QD-23", "6130-MC-01", "34-MCC-001", "1660-MC-01"]
    assert sum(1 for line in res.lines if line.bom_header_number == 40002) == 21


def test_other_plant_uses_sap_number(sample_bytes):
    res = build(sample_bytes, OTHER, None)
    assert res.lines[0].temp_number == 40001
    assert res.lines[1].temp_number == 10231307
    assert res.lines[1].planning_plant is None
    assert res.lines[1].sap_material_number == 10231307  # kept on the line, but no column in this template


def test_tag_sheet(sample_bytes):
    t = build(sample_bytes, DUKHAN).tags[0]
    assert (t.tag, t.submt, t.spir_no, t.rev, t.herst, t.typbz, t.mapar, t.serge, t.spir_type) == (
        "34-QD-23", 40001, "VEN-4391-M3TY-2-43-0003", "A", "SCHNEIDER ELECTRIC", "OKKEN", None, "A88029",
        "NORMAL OPERATING SPARES")


@pytest.mark.parametrize("plant_type", [DUKHAN, OTHER])
def test_templates_spir_number_keeps_revision(sample_bytes, plant_type):
    """CDC_SPIR NUMBER on the working and submission templates shows SPIR NO as in the input; the tag sheet,
    the material master and the file names keep the base number."""
    from app.services.excel_writer import TAG_SHEET, _sheet, write_submission

    s = get_settings()
    res = build(sample_bytes, plant_type)
    full, base = "VEN-4391-M3TY-2-43-0003-REV-A", "VEN-4391-M3TY-2-43-0003"
    assert {line.spir_number_full for line in res.lines} == {full}
    assert {line.spir_number for line in res.lines} == {base} and res.spir_numbers == [base]

    def column(ws, header, first_row):
        col = next(c.column for row in ws.iter_rows(max_row=first_row - 1) for c in row
                   if c.value and " ".join(str(c.value).split()).upper() == header)
        return {ws.cell(r, col).value for r in range(first_row, ws.max_row + 1)} - {None}

    wb = openpyxl.load_workbook(io.BytesIO(write_workbook(
        res, plant_type, s.template_dukhan if plant_type == DUKHAN else s.template_other)))
    assert column(wb["BOM WORKING TEMPLATE"], "CDC_SPIR NUMBER", 6) == {full}
    assert column(_sheet(wb, TAG_SHEET), "SPIR NO", 3) == {base}
    bom = wb["BOM WORKING TEMPLATE"]
    hdr = {" ".join(str(c.value).split()).upper(): c.column for c in bom[1] if c.value}
    eq_uom = {bom.cell(r, hdr["BASE UNIT OF MEASURE(T006)"]).value for r in range(6, bom.max_row + 1)
              if bom.cell(r, hdr["MATERIAL IS AN EQUIPMENT INDICATOR"]).value == "YES"}
    assert eq_uom == {"EA"}
    sub = openpyxl.load_workbook(io.BytesIO(write_submission(
        res, s.submission_dukhan if plant_type == DUKHAN else s.submission_other)))
    for name in ("BOM HEADER", "BOM PARTS", "MATERIAL MASTER"):
        assert column(sub[name], "CDC_SPIR NUMBER", 6) == {full}
    assert column(sub["BOM HEADER"], "BASE UNIT OF MEASURE(T006)", 6) == {"EA"}


def _styles(ws, rows):
    out = {}
    for r in rows:
        for c in ws[r]:
            out[c.coordinate] = (c.fill.fill_type, c.fill.fgColor.rgb, c.fill.fgColor.theme, c.fill.fgColor.tint,
                                 c.font.color.rgb if c.font.color else None, c.font.b)
    return out


@pytest.mark.parametrize("plant_type", [DUKHAN, OTHER])
def test_template_colours_unchanged(sample_bytes, plant_type):
    s = get_settings()
    tpl_path = s.template_dukhan if plant_type == DUKHAN else s.template_other
    res = build(sample_bytes, plant_type)
    out = openpyxl.load_workbook(io.BytesIO(write_workbook(res, plant_type, tpl_path)))
    tpl = openpyxl.load_workbook(tpl_path)

    t1, o1 = tpl["BOM WORKING TEMPLATE"], out["BOM WORKING TEMPLATE"]
    assert _styles(t1, range(1, 6)) == _styles(o1, range(1, 6))
    # the template's own conditional formatting is kept as-is; nothing is added
    # (openpyxl renumbers dxfId on save, so compare the actual differential style - fill/font/border)
    cf = lambda ws: sorted((str(k.sqref), [(r.type, r.formula, repr(ws.parent._differential_styles[r.dxfId]))  # noqa: E731
                                           for r in v])
                           for k, v in ws.conditional_formatting._cf_rules.items())
    assert cf(o1) == cf(t1)
    # data cells carry no new fill
    assert all(repr(c.fill) == repr(t1.cell(c.row, c.column).fill)
               for row in o1.iter_rows(min_row=6, max_row=79) for c in row)

    # tag sheet: original columns A-H keep their style, REMARKS moved one column right unchanged
    t2, o2 = tpl.worksheets[1], out.worksheets[1]
    for r in (1, 2):
        for col in range(1, 9):
            assert _styles(t2, [r])[t2.cell(r, col).coordinate] == _styles(o2, [r])[o2.cell(r, col).coordinate]
        assert o2.cell(r, 9).value == "SPIR TYPE"
        assert o2.cell(r, 10).value == t2.cell(r, 9).value  # REMARKS
        assert repr(o2.cell(r, 10).fill) == repr(t2.cell(r, 9).fill)
        assert repr(o2.cell(r, 9).fill) == repr(t2.cell(r, 8).fill)  # new column uses neighbour's header style


def test_written_values(sample_bytes):
    s = get_settings()
    res = build(sample_bytes, DUKHAN)
    ws = openpyxl.load_workbook(io.BytesIO(write_workbook(res, DUKHAN, s.template_dukhan)))["BOM WORKING TEMPLATE"]
    hdr = {str(c.value).strip(): c.column for c in ws[1] if c.value}
    assert ws.cell(7, hdr["SAP MATERIAL NUMBER"]).value == 10231307
    assert ws.cell(7, hdr["MATERIAL TEMP NUMBER"]).value == 10231307  # the SAP number
    assert ws.cell(7, hdr["LEN(MAT.DESC = 40)"]).value == "=LEN(I7)"
    assert ws.cell(79, hdr["SERIAL NUMBER"]).value == 74
    assert ws.cell(80, hdr["SERIAL NUMBER"]).value is None


@pytest.mark.parametrize("plant_type", [DUKHAN, OTHER])
def test_borders_and_frozen_header(sample_bytes, plant_type):
    s = get_settings()
    tpl_path = s.template_dukhan if plant_type == DUKHAN else s.template_other
    res = build(sample_bytes, plant_type)
    out = openpyxl.load_workbook(io.BytesIO(write_workbook(res, plant_type, tpl_path)))
    bom, tags = out["BOM WORKING TEMPLATE"], out.worksheets[1]

    assert bom.freeze_panes == "A6"   # rows 1-5 frozen
    assert tags.freeze_panes == "A3"  # rows 1-2 frozen

    def bordered(c):
        sides = (getattr(c.border, side) for side in ("left", "right", "top", "bottom"))
        return all(s is not None and s.style == "thin" for s in sides)

    for ws, first, last in ((bom, 6, 5 + len(res.lines)), (tags, 3, 2 + len(res.tags))):
        last_col = max(c.column for c in ws[1] if c.value is not None)
        table = [c for row in ws.iter_rows(min_row=first, max_row=last, max_col=last_col) for c in row]
        assert any(c.value is None for c in table)  # the table has empty cells, and they are bordered too
        assert all(bordered(c) for c in table)
        below = [c for row in ws.iter_rows(min_row=last + 1, max_row=ws.max_row) for c in row]
        assert not any(bordered(c) for c in below)  # the grid ends at the last data row


def test_spares_are_numbered_by_part_number():
    from app.services.input_reader import InputRow

    def row(n, tag, pn=None, **extra):
        values = {"TAG NO": tag, "QUANTITY IDENTICAL PARTS FITTED": "1", "MANUFACTURER PART NUMBER": pn, **extra}
        return InputRow(n, values)

    rows = [
        InputRow(1, {"TAG NO": "T-1", "EQPT QTY": "1"}),
        row(2, "T-1", "ABC123"),
        row(3, "T-1", "XYZ456"),
        InputRow(4, {"TAG NO": "T-2", "EQPT QTY": "1"}),
        row(5, "T-2", " abc123 "),                           # same part (case / spaces), other tag
        row(6, "T-2", "XYZ 456"),                            # a different part number
        row(7, "T-2", "ABC123", **{"SAP NUMBER": "999"}),    # a SAP NUMBER is used as it is (every plant)
    ]
    spares = [line.temp_number for line in build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {}).lines
              if line.category == "L"]
    assert spares == [500001, 500002, 500001, 500003, 999]


def test_equipment_is_numbered_by_part_number():
    from app.services.input_reader import InputRow

    def eq(n, tag, pn=None):
        return InputRow(n, {"TAG NO": tag, "EQPT QTY": "1", "MANUFACTURER PART NUMBER": pn})

    rows = [
        eq(1, "T-1", "JB82"),
        eq(2, "T-2", " jb82 "),     # same part (case / spaces), other tag -> same number
        eq(3, "T-3", "P50P9"),      # a different part number
        eq(4, "T-4"),               # no part number -> by tag
        eq(5, "T-5"),
        InputRow(6, {"TAG NO": "T-6", "QUANTITY IDENTICAL PARTS FITTED": "1",  # no equipment row: built from
                     "MANUFACTURER PART NUMBER": "JB82"}),                     # a spare -> by tag, not the spare's PN
    ]
    res = build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {})
    equipment = {line.tag: line.temp_number for line in res.lines if line.category == "B"}
    assert equipment == {"T-1": 40001, "T-2": 40001, "T-3": 40002, "T-4": 40003, "T-5": 40004, "T-6": 40005}
    assert [t.submt for t in res.tags] == [40001, 40001, 40002, 40003, 40004, 40005]


def test_equipment_and_spare_keep_separate_numbers_and_reuse_them():
    from app.services.input_reader import InputRow

    def eq(n, tag, pn):
        return InputRow(n, {"TAG NO": tag, "EQPT QTY": "1", "MANUFACTURER PART NUMBER": pn})

    def sp(n, tag, pn):
        return InputRow(n, {"TAG NO": tag, "QUANTITY IDENTICAL PARTS FITTED": "1", "MANUFACTURER PART NUMBER": pn})

    rows = [
        eq(1, "T-1", "EBAR10"),
        sp(2, "T-1", "EBAR10"),     # same part number as its equipment -> still a spare number of its own
        sp(3, "T-1", "O-RING"),
        eq(4, "T-2", "EBAR10"),     # the same equipment again (other tag) -> its number again
        sp(5, "T-2", "EBAR10"),     # the same spare again -> its number again
        sp(6, "T-2", "o-ring "),    # the same spare again (case / spaces) -> its number again
        eq(7, "T-3", "P50P9"),      # a new equipment -> new number
        sp(8, "T-3", "GASKET"),     # a new spare -> new number
    ]
    res = build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {})
    assert [(line.category, line.temp_number) for line in res.lines] == [
        ("B", 40001), ("L", 500001), ("L", 500002),
        ("B", 40001), ("L", 500001), ("L", 500002),
        ("B", 40002), ("L", 500003)]


def test_manufacturer_name_fits_30_whole_words():
    from app.services.bom_builder import fit_words
    from app.services.input_reader import InputRow

    assert fit_words("EMERSON PROCESS AUTOMATION, QATAR", 30) == "EMERSON PROCESS AUTOMATION"
    assert fit_words("SIEMENS", 30) == "SIEMENS"                      # short values are untouched
    assert fit_words("A" * 30, 30) == "A" * 30                        # exactly 30 is kept
    assert fit_words("ABCDEFGHIJ KLMNOPQRST UVWXYZABC D", 30) == "ABCDEFGHIJ KLMNOPQRST"
    assert fit_words("X" * 35, 30) == "X" * 30                        # one over-long word: length rule wins
    assert fit_words(None, 30) is None

    name = "EMERSON PROCESS AUTOMATION, QATAR"
    rows = [
        InputRow(1, {"TAG NO": "T-1", "EQPT QTY": "1", "EQPT MAKE": name, "SUPPLIER/ OCM NAME": name}),
        InputRow(2, {"TAG NO": "T-1", "QUANTITY IDENTICAL PARTS FITTED": "1", "MANUFACTURER PART NUMBER": "P1",
                     "SUPPLIER/ OCM NAME": name}),
    ]
    result = build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {})
    assert [line.mfr_name for line in result.lines] == ["EMERSON PROCESS AUTOMATION"] * 2
    assert result.tags[0].herst == name                               # TAG sheet keeps the full name
    assert [w.lines for w in result.warnings if w.code == "MFR_NAME_TOO_LONG"] == [[1, 2]]
    assert [line.add_information_text for line in result.lines] == [f"Manufacture name : {name}"] * 2


def test_equipment_manufacturer_name_is_eqpt_make():
    from app.services.input_reader import InputRow

    rows = [
        InputRow(1, {"TAG NO": "T-1", "EQPT QTY": "1", "EQPT MAKE": "JOBIRD",
                     "SUPPLIER/ OCM NAME": "INTERNATIONAL GULF TRADING"}),
        InputRow(2, {"TAG NO": "T-1", "QUANTITY IDENTICAL PARTS FITTED": "1", "EQPT MAKE": "JOBIRD",
                     "SUPPLIER/ OCM NAME": "INTERNATIONAL GULF TRADING"}),
        InputRow(3, {"TAG NO": "T-2", "EQPT QTY": "1", "SUPPLIER/ OCM NAME": "SIEMENS"}),  # no EQPT MAKE
        InputRow(4, {"TAG NO": "T-3", "QUANTITY IDENTICAL PARTS FITTED": "1", "EQPT MAKE": "ABB",  # no equipment
                     "SUPPLIER/ OCM NAME": "ABB QATAR"}),                                         # row (no EQPT QTY)
    ]
    result = build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {})
    assert [(line.tag, line.category, line.mfr_name) for line in result.lines] == [
        ("T-1", "B", "JOBIRD"), ("T-1", "L", "INTERNATIONAL GULF TRADING"),
        ("T-2", "B", None),
        ("T-3", "B", None), ("T-3", "L", "ABB QATAR")]
    assert [t.herst for t in result.tags] == ["JOBIRD", None, None]  # tag sheet: same EQPT MAKE rule


def test_add_information_keeps_part_number_and_full_name():
    from app.services.bom_builder import part_number_from_add_information
    from app.services.input_reader import InputRow

    long_pn = "P" * 40
    long_name = "EMERSON PROCESS AUTOMATION, QATAR"
    rows = [
        InputRow(1, {"TAG NO": "T-1", "EQPT QTY": "1", "SUPPLIER/ OCM NAME": "SIEMENS"}),
        InputRow(2, {"TAG NO": "T-1", "QUANTITY IDENTICAL PARTS FITTED": "1", "MANUFACTURER PART NUMBER": long_pn,
                     "SUPPLIER/ OCM NAME": long_name}),
        InputRow(3, {"TAG NO": "T-1", "QUANTITY IDENTICAL PARTS FITTED": "1", "MANUFACTURER PART NUMBER": long_pn,
                     "SUPPLIER/ OCM NAME": "SIEMENS"}),
    ]
    eq, both, pn_only = build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {}).lines
    assert eq.add_information_text is None                       # nothing to add -> empty, as before
    assert pn_only.add_information_text == long_pn               # part number only -> unchanged
    assert both.add_information_text == f"{long_pn} | Manufacture name : {long_name}"
    assert both.add_information == long_pn                       # material master still gets the part number
    for line in (eq, both, pn_only):
        assert part_number_from_add_information(line.add_information_text) == line.add_information
    assert part_number_from_add_information(f"Manufacture name : {long_name}") is None


@pytest.mark.parametrize("plant_type", [DUKHAN, OTHER])
def test_one_selected_tab(sample_bytes, plant_type):
    """Two selected tabs open in Excel's [Group] mode, where Filter and Sort are disabled."""
    from app.services.combiner import SUBMISSION, combine
    from app.services.excel_writer import write_submission

    settings = get_settings()
    result = build(sample_bytes, plant_type)
    working = write_workbook(result, plant_type,
                             settings.template_dukhan if plant_type == DUKHAN else settings.template_other)
    submission = write_submission(result,
                                  settings.submission_dukhan if plant_type == DUKHAN else settings.submission_other)

    # a submission made before the fix: BOM HEADER active, MATERIAL MASTER still selected from the template
    old = openpyxl.load_workbook(io.BytesIO(submission))
    for ws in old.worksheets:
        ws.sheet_view.tabSelected = True
    buf = io.BytesIO()
    old.save(buf)

    for content, active in ((working, "BOM WORKING TEMPLATE"), (submission, "BOM HEADER"),
                            (combine([buf.getvalue(), submission], SUBMISSION), "BOM HEADER")):
        wb = openpyxl.load_workbook(io.BytesIO(content))
        assert [ws.title.strip() for ws in wb.worksheets if ws.sheet_view.tabSelected] == [active]
        assert wb.active.title.strip() == active


@pytest.mark.parametrize("plant_type", [DUKHAN, OTHER])
def test_data_text_is_black(sample_bytes, plant_type):
    """The template pre-colours some LEN() cells red; every value in the data table must be black."""
    from app.services.combiner import SUBMISSION, WORKING, combine
    from app.services.excel_writer import write_submission

    settings = get_settings()
    result = build(sample_bytes, plant_type)
    working = write_workbook(result, plant_type,
                             settings.template_dukhan if plant_type == DUKHAN else settings.template_other)
    submission = write_submission(result,
                                  settings.submission_dukhan if plant_type == DUKHAN else settings.submission_other)

    def not_black(content):
        wb = openpyxl.load_workbook(io.BytesIO(content))
        bad = []
        for ws in wb.worksheets:
            first = 3 if ws.title.strip().upper() == "SPIR TAG VS SUBMT" else 6
            for row in ws.iter_rows(min_row=first):
                for c in row:
                    color = c.font.color
                    if c.value is not None and color is not None and not (color.type == "rgb" and color.rgb == "FF000000"):
                        bad.append(f"{ws.title}!{c.coordinate}")
        return bad

    for content in (working, submission, combine([working, working], WORKING),
                    combine([submission, submission], SUBMISSION)):
        assert not_black(content) == []

    # the header block keeps its template colours
    tpl = openpyxl.load_workbook(settings.template_dukhan if plant_type == DUKHAN else settings.template_other)
    out = openpyxl.load_workbook(io.BytesIO(working))
    for row in tpl.worksheets[0].iter_rows(max_row=5):
        for c in row:
            assert out.worksheets[0][c.coordinate].font.color == c.font.color


@pytest.mark.parametrize("plant_type", [DUKHAN, OTHER])
def test_equipment_old_material_is_qequ_plus_temp_number(sample_bytes, plant_type):
    res = build(sample_bytes, plant_type)
    equipment = [l for l in res.lines if l.category == "B"]
    assert equipment
    for line in equipment:
        assert line.old_material_number == f"QEQU-{line.temp_number}"
    # spares keep the OLD MATERIAL NUMBER/SPF NUMBER of their input row
    rows = {r.excel_row: r for r in read_input(sample_bytes)}
    for line in res.lines:
        if line.category == "L":
            assert line.old_material_number == rows[line.input_row].get("OLD MATERIAL NUMBER/SPF NUMBER")


def test_templates_list_each_unique_record_once():
    from app.services.excel_writer import TAG_SHEET, _sheet, write_submission
    from app.services.input_reader import InputRow

    def eq(n, tag):
        return InputRow(n, {"TAG NO": tag, "EQPT QTY": "1", "MANUFACTURER PART NUMBER": "EBAR10-2-T-316",
                            "DESCRIPTION OF PARTS": "EARTH BAR"})

    def sp(n, tag, pn, qty="1"):
        return InputRow(n, {"TAG NO": tag, "QUANTITY IDENTICAL PARTS FITTED": qty, "MANUFACTURER PART NUMBER": pn,
                            "DESCRIPTION OF PARTS": f"PART {pn}"})

    rows = []
    for i, tag in enumerate(["24-EB-0068", "24-EB-0069", "24-EB-0072"]):   # the same block three times
        rows += [eq(10 * i + 1, tag), sp(10 * i + 2, tag, "EBAR10-2-T-316"), sp(10 * i + 3, tag, "ELINK-T")]
    rows += [eq(41, "24-EB-0073"), sp(42, "24-EB-0073", "ELINK-T", qty="2"),  # same block, other quantity
             sp(43, "24-EB-0073", "NUT")]                                     # and a spare not listed yet
    result = build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {})
    assert len(result.lines) == 12 and len(result.tags) == 4                  # the conversion keeps every line

    s = get_settings()
    ws = openpyxl.load_workbook(io.BytesIO(write_workbook(result, DUKHAN, s.template_dukhan)))
    bom = ws["BOM WORKING TEMPLATE"]
    hdr = {str(c.value).strip(): c.column for c in bom[1] if c.value}
    got = [(bom.cell(r, hdr["SERIAL NUMBER"]).value, bom.cell(r, hdr["MATERIAL TEMP NUMBER"]).value,
            bom.cell(r, hdr["QUANTITY"]).value) for r in range(6, 11)]
    # one equipment block: B, its two spares (first quantity kept) and the new spare - renumbered 1..4
    assert got == [(1, 40001, 1), (2, 500001, 1), (3, 500002, 1), (4, 500003, 1), (None, None, None)]
    assert [w.lines for w in result.warnings if w.code == "QUANTITY_DIFFERS"] == [[42]]
    tag_sheet = _sheet(ws, TAG_SHEET)
    assert [tag_sheet.cell(r, 1).value for r in range(3, 7)] == ["24-EB-0068", "24-EB-0069", "24-EB-0072",
                                                                 "24-EB-0073"]   # every tag still mapped

    sub = openpyxl.load_workbook(io.BytesIO(write_submission(result, s.submission_dukhan)))
    count = lambda name: sum(1 for row in sub[name].iter_rows(min_row=6) if any(c.value is not None for c in row))  # noqa: E731
    assert (count("BOM HEADER"), count("BOM PARTS"), count("MATERIAL MASTER")) == (1, 3, 4)


def test_identical_spare_under_two_versions_of_an_equipment_is_listed_once():
    from app.services.excel_writer import unique_lines
    from app.services.input_reader import InputRow

    rows = []
    for i, (tag, qty) in enumerate([("PG-1", "131"), ("PG-2", "146")]):  # same equipment, other EQPT QTY
        rows += [InputRow(10 * i + 1, {"TAG NO": tag, "EQPT QTY": qty, "MANUFACTURER PART NUMBER": "LFBSPG"}),
                 InputRow(10 * i + 2, {"TAG NO": tag, "QUANTITY IDENTICAL PARTS FITTED": "1",
                                       "MANUFACTURER PART NUMBER": "GAUGE SAVER"})]
    out = unique_lines(build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {}).lines)
    # one temp number = one BOM header: the first tag's equipment line, the identical spare once under it
    assert [(ln.serial, ln.category, ln.temp_number, ln.quantity) for ln in out] == [
        (1, "B", 40001, 131), (2, "L", 500001, 1)]


def test_equipment_without_part_number_is_grouped_by_its_spares():
    from app.services.excel_writer import unique_lines
    from app.services.input_reader import InputRow

    def eq(n, tag, qty="1"):
        return InputRow(n, {"TAG NO": tag, "EQPT QTY": qty, "NEW DESCRIPTION OF PARTS": "LOCAL PANEL",
                            "SUPPLIER/ OCM NAME": "ESS"})

    def sp(n, tag, sap, pos, qty="2"):
        return InputRow(n, {"TAG NO": tag, "QUANTITY IDENTICAL PARTS FITTED": qty, "SAP NUMBER": sap,
                            "POSITION NUMBER": pos})

    rows = [eq(1, "LP-1", "8"), sp(2, "LP-1", "10636722", "0010"), sp(3, "LP-1", "10636723", "0020"),
            eq(4, "LP-2", "2"), sp(5, "LP-2", "10636722", "0030"), sp(6, "LP-2", "10636723", "0040"),  # same spares
            eq(7, "LP-3"), sp(8, "LP-3", "10636722", "0010"), sp(9, "LP-3", "10636723", "0020"),
            sp(10, "LP-3", "10636722", "0090"), sp(11, "LP-3", "10636723", "0100"),  # same spares, listed twice
            eq(12, "LP-4"), sp(13, "LP-4", "10636722", "0010"),                      # other spare set
            eq(14, "LP-5"), sp(15, "LP-5", "10636722", "0010", qty="5"),             # same set, other quantity
            eq(16, "LP-6"), eq(17, "LP-7")]                                          # no spares -> by tag
    res = build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {})
    assert [(t.tag, t.submt) for t in res.tags] == [("LP-1", 40001), ("LP-2", 40001), ("LP-3", 40001),
                                                   ("LP-4", 40002), ("LP-5", 40002), ("LP-6", 40003),
                                                   ("LP-7", 40004)]
    assert [w.lines for w in res.warnings if w.code == "REPEATED_SPARE"] == [[10, 11]]
    assert [w.lines for w in res.warnings if w.code == "QUANTITY_DIFFERS"] == [[15]]
    out = unique_lines(res.lines)
    # each spare once per header, with the first tag's quantity
    assert [(ln.category, ln.temp_number, ln.bom_header_number, ln.quantity) for ln in out] == [
        ("B", 40001, 40001, 8), ("L", 10636722, 40001, 2), ("L", 10636723, 40001, 2),
        ("B", 40002, 40002, 1), ("L", 10636722, 40002, 2),
        ("B", 40003, 40003, 1), ("B", 40004, 40004, 1)]


@pytest.mark.parametrize("plant_type", [DUKHAN, OTHER])
def test_spare_with_sap_number_3_or_8_is_category_n(plant_type):
    from app.services.excel_writer import write_submission
    from app.services.input_reader import InputRow, norm_header

    def row(n, tag, sap=None, equipment=False, pn=None):
        values = {"TAG NO": tag, "SAP NUMBER": sap, "MANUFACTURER PART NUMBER": pn or f"PN-{n}"}
        values.update({"EQPT QTY": "1"} if equipment else {"QUANTITY IDENTICAL PARTS FITTED": "1"})
        return InputRow(n, values)

    rows = [row(1, "T-1", "30161704", equipment=True),   # equipment with a 3... SAP number -> stays B
            row(2, "T-1", "30159733"), row(3, "T-1", "80012204"),   # spares 3... / 8... -> N
            row(4, "T-1", "10579834"), row(5, "T-1")]               # spare 1... / no SAP -> L
    result = build_bom(rows, plant_type, "DK01", InMemoryAllocator(), {})
    assert [ln.category for ln in result.lines] == ["B", "L", "L", "L", "L"]          # internal B / L unchanged
    assert [ln.type_category for ln in result.lines] == ["B", "N", "N", "L", "L"]
    assert (result.equipment_count, result.spare_count) == (1, 4)

    s = get_settings()
    wb = openpyxl.load_workbook(io.BytesIO(write_workbook(
        result, plant_type, s.template_dukhan if plant_type == DUKHAN else s.template_other)))
    ws = wb["BOM WORKING TEMPLATE"]
    col = {norm_header(c.value): c.column for c in ws[1] if c.value}[norm_header("MATERIAL TYPEVCATEGORY")]
    assert [ws.cell(r, col).value for r in range(6, 11)] == ["B", "N", "N", "L", "L"]
    sub = openpyxl.load_workbook(io.BytesIO(write_submission(
        result, s.submission_dukhan if plant_type == DUKHAN else s.submission_other)))
    mm = sub["MATERIAL MASTER"]
    mcol = {norm_header(c.value): c.column for c in mm[1] if c.value}[norm_header("MATERIAL TYPEVCATEGORY")]
    assert [mm.cell(r, mcol).value for r in range(6, 11)] == ["B", "N", "N", "L", "L"]


@pytest.mark.parametrize("plant_type", [DUKHAN, OTHER])
def test_sap_number_is_the_temp_number_in_every_plant(plant_type):
    from app.services.input_reader import InputRow

    rows = [InputRow(1, {"TAG NO": "T-1", "EQPT QTY": "1", "SAP NUMBER": "30161704"}),
            InputRow(2, {"TAG NO": "T-1", "QUANTITY IDENTICAL PARTS FITTED": "1", "SAP NUMBER": "10579834"}),
            InputRow(3, {"TAG NO": "T-1", "QUANTITY IDENTICAL PARTS FITTED": "1", "MANUFACTURER PART NUMBER": "X"}),
            InputRow(4, {"TAG NO": "T-2", "EQPT QTY": "1"})]
    lines = build_bom(rows, plant_type, "DK01", InMemoryAllocator(), {}).lines
    assert [(ln.category, ln.temp_number) for ln in lines] == [
        ("B", 30161704), ("L", 10579834), ("L", 500001),   # SAP numbers as they are; no SAP -> counter
        ("B", 40001)]                                      # the counters were not used for SAP lines
    assert lines[0].old_material_number == "QEQU-30161704" and lines[1].bom_header_number == 30161704


def test_category_n_when_the_reused_number_is_a_sap_number():
    """A spare without SAP NUMBER that reuses a SAP number from the material master (by part number)."""
    from dataclasses import replace
    from app.services.input_reader import InputRow

    rows = [InputRow(1, {"TAG NO": "T-1", "EQPT QTY": "1"}),
            InputRow(2, {"TAG NO": "T-1", "QUANTITY IDENTICAL PARTS FITTED": "1", "MANUFACTURER PART NUMBER": "X"})]
    spare = build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {}).lines[1]
    assert spare.type_category == "L"                                        # counter number 500001
    assert replace(spare, temp_number=30161704).type_category == "N"         # master's SAP number 3...
    assert replace(spare, temp_number=80012204).type_category == "N"         # 8...
    assert replace(spare, temp_number=10428450).type_category == "L"         # 1... SAP number
