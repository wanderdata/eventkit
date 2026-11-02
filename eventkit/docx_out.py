"""Render a summary markdown file to a clean Word document."""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))")


def _hyperlink(par, text, url):
    part = par.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                          is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), r_id)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    c = OxmlElement("w:color"); c.set(qn("w:val"), "1F5FAD"); rpr.append(c)
    u = OxmlElement("w:u"); u.set(qn("w:val"), "single"); rpr.append(u)
    r.append(rpr)
    t = OxmlElement("w:t"); t.text = text; t.set(qn("xml:space"), "preserve"); r.append(t)
    h.append(r)
    par._p.append(h)


def _inline(par, text, italic=False):
    for tok in INLINE.split(text):
        if not tok:
            continue
        if tok.startswith("**"):
            run = par.add_run(tok[2:-2]); run.bold = True; run.italic = italic
        elif tok.startswith("["):
            m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", tok)
            _hyperlink(par, m.group(1), m.group(2))
        elif tok.startswith("*"):
            run = par.add_run(tok[1:-1]); run.italic = True
        else:
            run = par.add_run(tok); run.italic = italic


def md_to_docx(md_path: Path, out_path: Path):
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(11)
    text = re.sub(r"<!--.*?-->\n?", "", md_path.read_text(encoding="utf-8"), flags=re.S)
    for block in [b.strip() for b in text.split("\n\n") if b.strip()]:
        if block.startswith("# "):
            p = doc.add_paragraph()
            r = p.add_run(block[2:].strip()); r.bold = True; r.font.size = Pt(16)
            r.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
        elif block.startswith("*") and block.endswith("*") and not block.startswith("**"):
            p = doc.add_paragraph()
            _inline(p, block[1:-1], italic=True)
        else:
            p = doc.add_paragraph()
            _inline(p, block.replace("\n", " "))
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_after = Pt(8)
    doc.save(out_path)
