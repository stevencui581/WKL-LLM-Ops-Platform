"""Render the V4.1 Markdown into a formatted DOCX using docx_helpers.

Layout (relative to the project root):
    docs/目标服务器LLM控制台开发方案V4.1.md  ->  docs/目标服务器LLM控制台开发方案V4.1.docx
    docs/assets/*.png                      ->  embedded figures
"""

import os
import re

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from docx_helpers import (
    CONTENT_W,
    DARK,
    GREEN,
    GREY,
    NAVY,
    RED,
    code,
    new_doc,
    set_widths,
    style_run,
)
from mdtext import brk, disp_len, plain

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
MD_NAME = "目标服务器LLM控制台开发方案V4.1.md"
DOCX_NAME = "目标服务器LLM控制台开发方案V4.1.docx"

CHECK = "\u2610"  # ballot box for task checklists
ARROW = "\u2192"


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
def split_row(line):
    """Split a markdown table row on unescaped pipes."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    out, buf, esc = [], [], False
    for ch in line:
        if esc:
            buf.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "|":
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf).strip())
    return out


def is_sep_row(line):
    s = line.replace("|", "").replace(" ", "").replace("-", "").replace(":", "")
    return s == "" and "-" in line


def parse_blocks(md):
    lines = md.split("\n")
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        if line.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(("code", "\n".join(buf)))
            continue

        if line.lstrip().startswith("|") and i + 1 < n and is_sep_row(lines[i + 1]):
            rows = [split_row(line)]
            i += 2
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            blocks.append(("table", rows))
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            blocks.append((f"h{len(m.group(1))}", m.group(2).strip()))
            i += 1
            continue

        if re.match(r"^---+$", line.strip()):
            i += 1
            continue

        m = re.match(r"^!\[(.*?)\]\((.*?)\)\s*$", line.strip())
        if m:
            blocks.append(("img", (m.group(1), m.group(2))))
            i += 1
            continue

        if line.startswith("> "):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(lines[i][1:].strip())
                i += 1
            blocks.append(("quote", " ".join(buf)))
            continue

        m = re.match(r"^- \[([ xX])\]\s+(.*)$", line)
        if m:
            blocks.append(("check", (m.group(1).lower() == "x", m.group(2))))
            i += 1
            continue

        if re.match(r"^[-*]\s+", line):
            blocks.append(("bullet", re.sub(r"^[-*]\s+", "", line)))
            i += 1
            continue

        if re.match(r"^\d+\.\s+", line):
            mnum = re.match(r"^(\d+)\.\s+(.*)$", line)
            blocks.append(("num", (mnum.group(1), mnum.group(2))))
            i += 1
            continue

        if not line.strip():
            i += 1
            continue

        buf = [line.strip()]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not re.match(r"^\s*(#{1,6}\s|```|\||>\s|- \[|- |\d+\.\s|!\[|---+$)", lines[i])
        ):
            buf.append(lines[i].strip())
            i += 1
        blocks.append(("p", " ".join(buf)))

    return blocks


# --------------------------------------------------------------------------
# inline rendering
# --------------------------------------------------------------------------
TOKEN = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")


def add_inline(p, text, size=10.5):
    for tok in TOKEN.split(text):
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            style_run(p.add_run(tok[2:-2]), size=size, bold=True)
        elif tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
            style_run(p.add_run(tok[1:-1]), size=size - 0.5, mono=True)
        elif tok.startswith("[") and "](" in tok and tok.endswith(")"):
            label, url = tok[1:-1].split("](", 1)
            style_run(p.add_run(label), size=size, color=NAVY)
            style_run(p.add_run(" " + url), size=size - 1.5, color=GREY)
        else:
            style_run(p.add_run(tok), size=size)
    return p


# --------------------------------------------------------------------------
# document
# --------------------------------------------------------------------------
def compute_widths(rows, total):
    ncol = max(len(r) for r in rows)
    lens = []
    for c in range(ncol):
        m = max((disp_len(plain(r[c])) if c < len(r) else 0) for r in rows)
        lens.append(max(4, m))
    s = float(sum(lens))
    raw = [total * v / s for v in lens]
    lo, hi = 0.5, 4.0
    for _ in range(3):
        raw = [min(hi, max(lo, w)) for w in raw]
        s2 = sum(raw)
        raw = [w * total / s2 for w in raw]
    return raw


DEFAULT_FOOTER = "WKL-LLM运维平台 v0.1  ·  目标服务器 LLM 控制台开发方案 V4.1  ·  内部技术文档"


def build(md_path, out_path, asset_dir, footer_text=DEFAULT_FOOTER):
    with open(md_path, encoding="utf-8") as f:
        md = f.read()
    blocks = parse_blocks(md)

    doc = new_doc()
    ft = doc.sections[0].footer.paragraphs[0]
    ft.alignment = WD_ALIGN_PARAGRAPH.CENTER
    style_run(ft.add_run(footer_text), size=8, color=GREY)

    first_title = True
    ntab = 0
    for kind, payload in blocks:
        if kind == "h1":
            if first_title:
                p = doc.add_paragraph()
                style_run(p.add_run(plain(payload)), size=19, bold=True, color=NAVY)
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_after = Pt(8)
                first_title = False
            else:
                p = doc.add_paragraph()
                style_run(p.add_run(plain(payload)), size=17, bold=True, color=NAVY)
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(10)
                p.paragraph_format.space_after = Pt(10)
                p.paragraph_format.page_break_before = True
            continue

        if kind == "h2":
            p = doc.add_heading(plain(payload), level=1)
            for r in p.runs:
                style_run(r, size=15, bold=True, color=NAVY)
            p.paragraph_format.space_before = Pt(16)
            p.paragraph_format.space_after = Pt(6)
            continue

        if kind == "h3":
            p = doc.add_heading(plain(payload), level=2)
            for r in p.runs:
                style_run(r, size=12.5, bold=True, color=NAVY)
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(4)
            continue

        if kind == "h4":
            p = doc.add_heading(plain(payload), level=3)
            for r in p.runs:
                style_run(r, size=11.5, bold=True, color=DARK)
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(3)
            continue

        if kind in ("h5", "h6"):
            p = doc.add_heading(plain(payload), level=4)
            for r in p.runs:
                style_run(r, size=10.5, bold=True, color=DARK)
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(2)
            continue

        if kind == "p":
            p = doc.add_paragraph()
            add_inline(p, payload, size=10.5)
            p.paragraph_format.space_after = Pt(4)
            continue

        if kind == "bullet":
            p = doc.add_paragraph(style="List Bullet")
            add_inline(p, payload, size=10.5)
            p.paragraph_format.space_after = Pt(2)
            continue

        if kind == "num":
            num, text = payload
            p = doc.add_paragraph()
            style_run(p.add_run(num + ". "), size=10.5)
            add_inline(p, text, size=10.5)
            p.paragraph_format.left_indent = Inches(0.3)
            p.paragraph_format.first_line_indent = Inches(-0.3)
            p.paragraph_format.space_after = Pt(2)
            continue

        if kind == "check":
            done, text = payload
            p = doc.add_paragraph(style="List Bullet")
            style_run(
                p.add_run((CHECK + "  ") if not done else ("\u2611" + "  ")),
                size=11,
                color=GREEN if done else GREY,
            )
            add_inline(p, text, size=10)
            p.paragraph_format.space_after = Pt(2)
            continue

        if kind == "quote":
            t = doc.add_table(rows=1, cols=1)
            t.style = "Table Grid"
            c = t.rows[0].cells[0]
            c.text = ""
            from docx_helpers import shade

            shade(c, "EEF4FA")
            pp = c.paragraphs[0]
            add_inline(pp, payload, size=9.5)
            for r in pp.runs:
                r.font.color.rgb = DARK
            pp.paragraph_format.space_after = Pt(1)
            set_widths(t, [CONTENT_W])
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
            continue

        if kind == "code":
            code(doc, payload, size=7.4)
            continue

        if kind == "img":
            alt, rel = payload
            path = os.path.join(asset_dir, os.path.basename(rel))
            if os.path.exists(path):
                doc.add_picture(path, width=Inches(6.1))
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                cp = doc.add_paragraph()
                style_run(cp.add_run(alt), size=9, color=GREY)
                cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                cp.paragraph_format.space_after = Pt(6)
            else:
                p = doc.add_paragraph()
                style_run(p.add_run(f"[缺图: {rel}]"), size=9, color=RED)
            continue

        if kind == "table":
            rows = [[brk(c.replace("<br>", " / ")) for c in r] for r in payload]
            ncol = max(len(r) for r in rows)
            rows = [r + [""] * (ncol - len(r)) for r in rows]
            widths = compute_widths(rows, CONTENT_W)
            size = 9 if ncol <= 3 else (8.5 if ncol <= 5 else 7.5)
            ntab += 1
            # render header row plainly (no bold markers), body with inline
            t = doc.add_table(rows=len(rows), cols=ncol)
            t.style = "Table Grid"
            from docx.enum.table import WD_TABLE_ALIGNMENT

            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            from docx_helpers import polish_table, shade

            for ri, r in enumerate(rows):
                for ci in range(ncol):
                    cell = t.rows[ri].cells[ci]
                    cell.text = ""
                    p = cell.paragraphs[0]
                    if ri == 0:
                        style_run(
                            p.add_run(plain(r[ci])),
                            size=size + 0.5,
                            bold=True,
                            color=RGBColor(0xFF, 0xFF, 0xFF),
                        )
                        shade(cell, "1F4E79")
                    else:
                        add_inline(p, r[ci], size=size)
                        if ri % 2 == 0:
                            shade(cell, "EEF4FA")
                    p.paragraph_format.space_after = Pt(1)
            set_widths(t, widths)
            polish_table(t)
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
            continue

    doc.save(out_path)
    print("saved:", out_path)
    print("blocks rendered, tables:", ntab)


if __name__ == "__main__":
    import sys

    # 允许指定输入/输出/页脚（默认仍是 V4.1，保持既有构建不变）
    md = sys.argv[1] if len(sys.argv) > 1 else MD_NAME
    out = sys.argv[2] if len(sys.argv) > 2 else DOCX_NAME
    footer = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_FOOTER
    build(os.path.join(DOCS, md), os.path.join(DOCS, out), os.path.join(DOCS, "assets"), footer_text=footer)
