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
    assert sp.sap_material_number == 10231307 and sp.temp_number == 500001
    assert sp.bom_header_number == 40001 and sp.quantity == 4 and sp.position_number == "0010"
    assert sp.spir_number == "VEN-4391-M3TY-2-43-0003"
    assert sp.uom == "NO" and sp.currency == "QAR" and sp.country_code == "QA" and sp.country_name == "QATAR"
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
    assert ws.cell(7, hdr["MATERIAL TEMP NUMBER"]).value == 500001
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
        row(5, "T-2", " abc123 ", **{"SAP NUMBER": "999"}),  # same part (case / spaces), other tag + SAP
        row(6, "T-2", "XYZ 456"),                            # a different part number
    ]
    spares = [line.temp_number for line in build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {}).lines
              if line.category == "L"]
    assert spares == [500001, 500002, 500001, 500003]


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
        InputRow(1, {"TAG NO": "T-1", "EQPT QTY": "1", "SUPPLIER/ OCM NAME": name}),
        InputRow(2, {"TAG NO": "T-1", "QUANTITY IDENTICAL PARTS FITTED": "1", "MANUFACTURER PART NUMBER": "P1",
                     "SUPPLIER/ OCM NAME": name}),
    ]
    result = build_bom(rows, DUKHAN, "DK01", InMemoryAllocator(), {})
    assert [line.mfr_name for line in result.lines] == ["EMERSON PROCESS AUTOMATION"] * 2
    assert result.tags[0].herst == name                               # TAG sheet keeps the full name
    assert [w.lines for w in result.warnings if w.code == "MFR_NAME_TOO_LONG"] == [[1, 2]]
    assert [line.add_information_text for line in result.lines] == [f"Manufacture name : {name}"] * 2


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
