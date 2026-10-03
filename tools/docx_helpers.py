"""Shared python-docx helpers for the 253 server LLM console plan documents."""

from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

CJK = "微软雅黑"
MONO = "Consolas"
NAVY = RGBColor(0x1F, 0x4E, 0x79)
DARK = RGBColor(0x26, 0x32, 0x38)
GREY = RGBColor(0x60, 0x6A, 0x74)
RED = RGBColor(0xC0, 0x39, 0x2B)
GREEN = RGBColor(0x1E, 0x7A, 0x46)
ORANGE = RGBColor(0xB9, 0x77, 0x0A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

#: printable content width for A4 with 0.86 in side margins
CONTENT_W = 8.27 - 0.86 * 2  # 6.55 in

_TBLPR_SEQ = [
    "w:tblStyle",
    "w:tblpPr",
    "w:tblOverlap",
    "w:bidiVisual",
    "w:tblStyleRowBandSize",
    "w:tblStyleColBandSize",
    "w:tblW",
    "w:jc",
    "w:tblCellSpacing",
    "w:tblInd",
    "w:tblBorders",
    "w:shd",
    "w:tblLayout",
    "w:tblCellMar",
    "w:tblLook",
    "w:tblCaption",
    "w:tblDescription",
    "w:tblPrChange",
]


def style_run(run, size=10.5, bold=False, color=None, font=None, mono=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    name = MONO if mono else (font or CJK)
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rf)
    rf.set(qn("w:ascii"), name)
    rf.set(qn("w:hAnsi"), name)
    rf.set(qn("w:eastAsia"), CJK)
    return run


def para(doc, text="", size=10.5, bold=False, color=None, align=None, style=None, space_after=4, mono=False):
    p = doc.add_paragraph(style=style) if style else doc.add_paragraph()
    if text:
        style_run(p.add_run(text), size=size, bold=bold, color=color, mono=mono)
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    return p


def rich(doc, parts, size=10.5, space_after=4, style=None):
    p = doc.add_paragraph(style=style) if style else doc.add_paragraph()
    for text, opt in parts:
        style_run(
            p.add_run(text),
            size=opt.get("size", size),
            bold=opt.get("bold", False),
            color=opt.get("color"),
            mono=opt.get("mono", False),
        )
    p.paragraph_format.space_after = Pt(space_after)
    return p


def h1(doc, text):
    p = doc.add_heading(text, level=1)
    for r in p.runs:
        style_run(r, size=15, bold=True, color=NAVY)
    p.paragraph_format.space_before = Pt(16)
    p.paragraph_format.space_after = Pt(6)
    return p


def h1_new_page(doc, text):
    """Level-1 heading that starts a new page without an extra empty paragraph."""
    p = h1(doc, text)
    p.paragraph_format.page_break_before = True
    return p


def h2(doc, text):
    p = doc.add_heading(text, level=2)
    for r in p.runs:
        style_run(r, size=12.5, bold=True, color=NAVY)
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    return p


def h3(doc, text):
    p = doc.add_heading(text, level=3)
    for r in p.runs:
        style_run(r, size=11, bold=True, color=DARK)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(3)
    return p


def bullet(doc, text, lead=None, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    if lead:
        style_run(p.add_run(lead), size=size, bold=True)
    style_run(p.add_run(text), size=size)
    p.paragraph_format.space_after = Pt(2)
    return p


def numbered(doc, text, lead=None, size=10.5):
    p = doc.add_paragraph(style="List Number")
    if lead:
        style_run(p.add_run(lead), size=size, bold=True)
    style_run(p.add_run(text), size=size)
    p.paragraph_format.space_after = Pt(2)
    return p


def bullets(doc, items, size=10.5):
    for it in items:
        lead, txt = it if isinstance(it, tuple) else (None, it)
        bullet(doc, txt, lead, size)


def shade(cell, color):
    tcpr = cell._element.get_or_add_tcPr()
    shd = tcpr.makeelement(qn("w:shd"), {qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): color})
    tcpr.append(shd)


def _insert_ordered(parent, element, tag):
    idx = _TBLPR_SEQ.index(tag)
    for child in list(parent):
        ctag = "w:" + child.tag.split("}")[-1]
        if ctag in _TBLPR_SEQ and _TBLPR_SEQ.index(ctag) > idx:
            child.addprevious(element)
            return
    parent.append(element)


def set_widths(table, widths_in):
    """Fixed table layout + explicit grid: never auto-expand past the margin."""
    table.autofit = False
    tbl = table._tbl
    tblPr = tbl.tblPr
    for tag in ("w:tblLayout", "w:tblW"):
        for el in tblPr.findall(qn(tag)):
            tblPr.remove(el)
    total = int(round(sum(widths_in) * 1440))
    _insert_ordered(
        tblPr, tblPr.makeelement(qn("w:tblW"), {qn("w:w"): str(total), qn("w:type"): "dxa"}), "w:tblW"
    )
    _insert_ordered(tblPr, tblPr.makeelement(qn("w:tblLayout"), {qn("w:type"): "fixed"}), "w:tblLayout")

    old = tbl.find(qn("w:tblGrid"))
    if old is not None:
        tbl.remove(old)
    grid = tbl.makeelement(qn("w:tblGrid"), {})
    for w in widths_in:
        grid.append(grid.makeelement(qn("w:gridCol"), {qn("w:w"): str(int(round(w * 1440)))}))
    tblPr.addnext(grid)

    for row in table.rows:
        for i, w in enumerate(widths_in):
            if i < len(row.cells):
                row.cells[i].width = Inches(w)


def polish_table(table):
    tr = table.rows[0]._tr
    trPr = tr.get_or_add_trPr()
    trPr.append(trPr.makeelement(qn("w:tblHeader"), {qn("w:val"): "true"}))
    for row in table.rows:
        rpr = row._tr.get_or_add_trPr()
        rpr.append(rpr.makeelement(qn("w:cantSplit"), {qn("w:val"): "true"}))


def make_table(doc, headers, rows, widths, size=9, header_fill="1F4E79", zebra=True):
    t = doc.add_table(rows=len(rows) + 1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, htxt in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        style_run(c.paragraphs[0].add_run(htxt), size=size + 0.5, bold=True, color=WHITE)
        c.paragraphs[0].paragraph_format.space_after = Pt(1)
        shade(c, header_fill)
    for ri, row in enumerate(rows, 1):
        for ci, val in enumerate(row):
            c = t.rows[ri].cells[ci]
            c.text = ""
            p = c.paragraphs[0]
            txt = str(val)
            if txt.startswith("`") and txt.endswith("`") and len(txt) > 1:
                style_run(p.add_run(txt[1:-1].replace("`", "")), size=size - 0.5, mono=True)
            else:
                style_run(p.add_run(txt.replace("`", "")), size=size)
            p.paragraph_format.space_after = Pt(1)
            if zebra and ri % 2 == 0:
                shade(c, "EEF4FA")
    set_widths(t, widths)
    polish_table(t)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def code(doc, text, size=8, color=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.space_before = Pt(2)
    first = True
    for line in text.split("\n"):
        if not first:
            p.add_run().add_break()
        first = False
        style_run(p.add_run(line), size=size, mono=True, color=color)
    return p


def banner(doc, title, body, color="FFF4E5", bar="B9770A"):
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    c = t.rows[0].cells[0]
    c.text = ""
    shade(c, color)
    p1 = c.paragraphs[0]
    style_run(p1.add_run(title), size=10.5, bold=True, color=RGBColor.from_string(bar))
    p1.paragraph_format.space_after = Pt(2)
    p2 = c.add_paragraph()
    style_run(p2.add_run(body), size=9.5)
    p2.paragraph_format.space_after = Pt(1)
    set_widths(t, [CONTENT_W])
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def caption(doc, text):
    return para(doc, text, size=9, color=GREY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)


def picture(doc, path, width_in=6.1):
    doc.add_picture(path, width=Inches(width_in))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    para(doc, "", size=6, space_after=6)


def new_doc():
    from docx import Document

    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Inches(8.27)
    sec.page_height = Inches(11.69)
    sec.left_margin = sec.right_margin = Inches(0.86)
    sec.top_margin = sec.bottom_margin = Inches(0.8)
    return doc
