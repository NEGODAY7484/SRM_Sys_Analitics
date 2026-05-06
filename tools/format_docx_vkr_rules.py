"""
Format an existing DOCX to match the VKR formatting rules.

The rules source is the document stored in this repo (see docs/vkr_rules.docx).
This script keeps document content intact, but normalizes:
  - page settings (margins, header/footer distance),
  - base styles (Times New Roman 13, 1.5 spacing, indent),
  - heading styles (sizes/spacings per rules),
  - table text (11pt, single spacing),
  - page numbering (footer, hidden on first section, start at N on the next).

Note: we avoid hard-coded Cyrillic in the source file to prevent console/codepage
issues on Windows; Russian strings are expressed via Unicode escapes.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def _ru(s: str) -> str:
    """Decode a '\\uXXXX' escape string into Unicode text."""

    return s.encode("ascii").decode("unicode_escape")


INTRO = _ru("\\u0412\\u0432\\u0435\\u0434\\u0435\\u043d\\u0438\\u0435")  # "Введение"
CONCLUSION = _ru(
    "\\u0417\\u0430\\u043a\\u043b\\u044e\\u0447\\u0435\\u043d\\u0438\\u0435"
)  # "Заключение"
ANNOTATION = _ru("\\u0410\\u043d\\u043d\\u043e\\u0442\\u0430\\u0446\\u0438\\u044f")  # "Аннотация"

WORD_LIST = _ru("\\u0441\\u043f\\u0438\\u0441\\u043e\\u043a")  # "список"
WORD_SOURCES_PREFIX = _ru("\\u0438\\u0441\\u0442\\u043e\\u0447")  # "источ..."

WORD_FIG_PREFIX = _ru("\\u0440\\u0438\\u0441")  # "рис"
WORD_FIG = _ru("\\u0420\\u0438\\u0441\\u0443\\u043d\\u043e\\u043a")  # "Рисунок"
WORD_TABLE = _ru("\\u0422\\u0430\\u0431\\u043b\\u0438\\u0446\\u0430")  # "Таблица"


def _set_vkr_styles(doc) -> None:
    """Apply base styles according to the rules (TNR 13, 1.5, etc.)."""

    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    # A4 portrait is the default in most documents. Here we enforce margins + distances.
    for sec in doc.sections:
        sec.top_margin = Cm(2.0)
        sec.bottom_margin = Cm(2.0)
        sec.left_margin = Cm(3.0)
        sec.right_margin = Cm(1.5)
        # Header/footer distance (колонтитулы): верхний 1.5 см, нижний 1.25 см
        sec.header_distance = Cm(1.5)
        sec.footer_distance = Cm(1.25)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(13)
    pf = normal.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.line_spacing = 1.5
    pf.first_line_indent = Cm(1.25)
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)

    # Headings (rules section 3.1)
    # H1: 16 bold, before 0, after 12
    h1 = doc.styles["Heading 1"]
    h1.font.name = "Times New Roman"
    h1.font.size = Pt(16)
    h1.font.bold = True
    h1.paragraph_format.first_line_indent = Cm(0)
    h1.paragraph_format.space_before = Pt(0)
    h1.paragraph_format.space_after = Pt(12)

    # H2: 14 bold, before 12, after 6
    h2 = doc.styles["Heading 2"]
    h2.font.name = "Times New Roman"
    h2.font.size = Pt(14)
    h2.font.bold = True
    h2.paragraph_format.first_line_indent = Cm(0)
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after = Pt(6)

    # H3: 13 bold, before 8, after 4
    h3 = doc.styles["Heading 3"]
    h3.font.name = "Times New Roman"
    h3.font.size = Pt(13)
    h3.font.bold = True
    h3.paragraph_format.first_line_indent = Cm(0)
    h3.paragraph_format.space_before = Pt(8)
    h3.paragraph_format.space_after = Pt(4)


def _looks_like_numbered_heading(text: str) -> tuple[int, str] | None:
    """Return (level, cleaned_text) if paragraph looks like '1.'/'1.2.' heading."""

    import re

    t = (text or "").strip()
    if len(t) > 140:
        return None

    m = re.match(r"^(\d+(?:\.\d+)*)\.\s+(.*)$", t)
    if not m:
        return None

    num = m.group(1)
    rest = m.group(2).strip()
    if not rest:
        return None

    parts = num.split(".")
    level = 1 if len(parts) <= 1 else 2 if len(parts) == 2 else 3
    return level, f"{num}. {rest}"


def _normalize_paragraphs(doc) -> None:
    """Normalize headings/lists/captions while keeping existing content intact."""

    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    bullet_minus = "\u2212"  # "−"
    en_dash = "\u2013"  # "–"

    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if not t:
            continue

        # Headings by numbering (e.g. "2.3. ...").
        hd = _looks_like_numbered_heading(t)
        if hd:
            level, cleaned = hd
            p.text = cleaned
            p.style = f"Heading {level}"
            p.paragraph_format.first_line_indent = Cm(0)
            continue

        lowered = t.casefold()

        # Unnumbered key sections.
        if lowered.startswith(INTRO.casefold()):
            p.text = INTRO
            p.style = "Heading 1"
            p.paragraph_format.first_line_indent = Cm(0)
            continue
        if lowered.startswith(CONCLUSION.casefold()):
            p.text = CONCLUSION
            p.style = "Heading 1"
            p.paragraph_format.first_line_indent = Cm(0)
            continue
        if WORD_LIST in lowered and WORD_SOURCES_PREFIX in lowered:
            p.style = "Heading 1"
            p.paragraph_format.first_line_indent = Cm(0)
            continue

        # Lists: in the rules marker should be a dash. We keep existing list markers,
        # but enforce indents so the output matches the rule visually.
        if t.startswith((bullet_minus, "-", en_dash)):
            p.paragraph_format.left_indent = Cm(2.0)
            p.paragraph_format.first_line_indent = Cm(1.5)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            continue

        # Captions: "Рисунок ..." centered; "Таблица ..." left, without indent.
        if lowered.startswith((WORD_FIG_PREFIX, WORD_FIG.casefold())):
            # Normalize common short forms: "Рис " / "Рис."
            if lowered.startswith(WORD_FIG_PREFIX + " "):
                p.text = WORD_FIG + t[len(WORD_FIG_PREFIX) :]
            elif lowered.startswith(WORD_FIG_PREFIX + "."):
                p.text = WORD_FIG + t[len(WORD_FIG_PREFIX) + 1 :]
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.0
            continue
        if lowered.startswith(WORD_TABLE.casefold()):
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.0
            continue


def _set_tables_style(doc) -> None:
    """Tables: 11pt, single spacing (rules section 3.3)."""

    from docx.shared import Pt

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.line_spacing = 1.0
                    for r in p.runs:
                        r.font.name = "Times New Roman"
                        r.font.size = Pt(11)  # within 11–12 range


def _add_page_field(paragraph) -> None:
    """Insert a PAGE field into a paragraph (OOXML field codes)."""

    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")

    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "

    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")

    text = OxmlElement("w:t")
    text.text = "1"  # placeholder; Word updates it

    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(text)
    run._r.append(fld_end)


def _clear_paragraph(paragraph) -> None:
    """Remove all runs from a paragraph, preserving paragraph properties."""

    p = paragraph._p  # noqa: SLF001 (python-docx internal)
    for child in list(p):
        if child.tag.endswith("}pPr"):
            continue
        p.remove(child)


def _set_section_page_start(section, start: int) -> None:
    """Set page numbering start for a section (w:pgNumType)."""

    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    sectPr = section._sectPr  # noqa: SLF001 (python-docx internal)
    pg = sectPr.find(qn("w:pgNumType"))
    if pg is None:
        pg = OxmlElement("w:pgNumType")
        sectPr.append(pg)
    pg.set(qn("w:start"), str(start))


def _move_last_section_break_to_paragraph(doc, paragraph_index: int) -> None:
    """
    python-docx can only add sections at the end. This helper:
      1) adds a new section at the end,
      2) takes the generated section-break <w:sectPr> from the last paragraph,
      3) moves it into the target paragraph,
      4) removes the now-empty last paragraph (created by python-docx).
    """

    from docx.enum.section import WD_SECTION

    doc.add_section(WD_SECTION.NEW_PAGE)

    body = doc._element.body  # noqa: SLF001
    paragraphs = body.xpath("./w:p")
    last_p = paragraphs[-1]
    sect_pr = last_p.xpath("./w:pPr/w:sectPr")
    if not sect_pr:
        raise RuntimeError("Cannot find generated section break (<w:sectPr>) to move.")
    sect_pr = sect_pr[0]

    target_p = doc.paragraphs[paragraph_index]._p  # noqa: SLF001
    ppr = target_p.get_or_add_pPr()

    for existing in target_p.xpath("./w:pPr/w:sectPr"):
        existing.getparent().remove(existing)
    ppr.append(sect_pr)

    last_p.getparent().remove(last_p)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Format an existing DOCX to VKR rules.")
    p.add_argument("--in", dest="inp", type=Path, required=True, help="Input DOCX")
    p.add_argument("--out", type=Path, required=True, help="Output DOCX")
    p.add_argument(
        "--split-before",
        type=str,
        default=INTRO,
        help="Start page numbering from a new section before this heading (default: 'Введение').",
    )
    p.add_argument(
        "--start-page",
        type=int,
        default=3,
        help="First visible page number after split (default: 3).",
    )
    return p.parse_args()


def main() -> int:
    try:
        from docx import Document  # type: ignore
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK  # type: ignore
        from docx.shared import Cm  # type: ignore
    except Exception as e:  # pragma: no cover
        print('Missing dependency. Install with: python -m pip install -e ".[report]"')
        print(f"Import error: {e}")
        return 2

    args = parse_args()
    doc = Document(str(args.inp))

    _set_vkr_styles(doc)

    # Find split location for front-matter vs main content.
    split_idx: int | None = None
    needle = (args.split_before or INTRO).casefold()
    for i, p in enumerate(doc.paragraphs):
        if (p.text or "").casefold().strip().startswith(needle):
            split_idx = max(0, i - 1)
            break
    if split_idx is None:
        for i, p in enumerate(doc.paragraphs):
            if _looks_like_numbered_heading(p.text or ""):
                split_idx = max(0, i - 1)
                break
    if split_idx is None:
        split_idx = 0

    # Insert a page break before "Аннотация" (if present early).
    for i, p in enumerate(doc.paragraphs[:120]):
        if (p.text or "").strip().casefold() == ANNOTATION.casefold():
            j = i - 1
            while j >= 0 and not (doc.paragraphs[j].text or "").strip():
                j -= 1
            if j >= 0:
                doc.paragraphs[j].add_run().add_break(WD_BREAK.PAGE)
            break

    # Create two sections and add page numbering in the 2nd section footer.
    if len(doc.sections) == 1:
        _move_last_section_break_to_paragraph(doc, split_idx)

    sec0 = doc.sections[0]
    sec1 = doc.sections[1] if len(doc.sections) > 1 else doc.sections[0]

    # Footer: hide on section 0, show on section 1 (bottom center).
    try:
        sec1.footer.is_linked_to_previous = False
    except Exception:
        pass
    footer_p = sec1.footer.paragraphs[0] if sec1.footer.paragraphs else sec1.footer.add_paragraph()
    _clear_paragraph(footer_p)
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_field(footer_p)

    try:
        sec0.footer.is_linked_to_previous = False
    except Exception:
        pass
    if sec0.footer.paragraphs:
        _clear_paragraph(sec0.footer.paragraphs[0])

    if sec1 is not sec0:
        _set_section_page_start(sec1, args.start_page)

    if 0 <= split_idx < len(doc.paragraphs):
        # section break already forces a new page; clean huge whitespace paragraphs if present.
        if (doc.paragraphs[split_idx].text or "").count("\n") > 3:
            doc.paragraphs[split_idx].text = ""
        doc.paragraphs[split_idx].paragraph_format.first_line_indent = Cm(0)

    _normalize_paragraphs(doc)
    _set_tables_style(doc)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
