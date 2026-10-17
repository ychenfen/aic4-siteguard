"""把 docs/paper/论文.md 转成 Word（需要 pandoc 与 python-docx），并按中文论文习惯设置字体字号。

    python scripts/build_paper.py

正文宋体小四、1.5 倍行距、首行缩进 2 字符；标题黑体；英文与数字 Times New Roman；图片居中。
若比赛提供模板，可用 `pandoc --reference-doc=模板.docx` 替换样式。
"""
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "docs" / "paper"
SRC, OUT = PAPER / "论文.md", PAPER / "论文.docx"

subprocess.run(["pandoc", SRC.name, "-o", OUT.name, "--resource-path=.", "--toc", "--toc-depth=2",
                "-M", "toc-title=目录"], cwd=PAPER, check=True)

doc = Document(OUT)


def set_font(style_or_run, east, west="Times New Roman", size=None, bold=None):
    f = style_or_run.font
    f.name = west
    if size:
        f.size = Pt(size)
    if bold is not None:
        f.bold = bold
    el = style_or_run.element
    rpr = el.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for k in ("w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(k), west)
    rfonts.set(qn("w:eastAsia"), east)
    for k in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if rfonts.get(qn(k)) is not None:
            del rfonts.attrib[qn(k)]


styles = doc.styles
BY_NAME = {s.name: s for s in styles}


def get(name):
    return BY_NAME.get(name)


for name in ("Normal", "Body Text", "First Paragraph", "Compact"):
    st = get(name)
    if st is not None:
        set_font(st, "宋体", size=12)
        pf = st.paragraph_format
        pf.line_spacing = 1.5
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        if name in ("Body Text", "First Paragraph"):
            pf.first_line_indent = Pt(24)
sizes = {"Title": 18, "Subtitle": 12, "Heading 1": 16, "Heading 2": 14, "Heading 3": 12}
for name, sz in sizes.items():
    st = get(name)
    if st is not None:
        set_font(st, "黑体", size=sz, bold=True)
        st.font.color.rgb = None
        st.paragraph_format.space_before = Pt(12)
        st.paragraph_format.space_after = Pt(6)
        if name in ("Title", "Subtitle"):
            st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
for name in ("Image Caption", "Captioned Figure", "Figure"):
    st = get(name)
    if st is not None:
        set_font(st, "宋体", size=10.5)
        st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        st.paragraph_format.first_line_indent = Pt(0)

for p in doc.paragraphs:
    if p._element.xpath(".//w:drawing"):
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Pt(0)
    t = p.text.strip()
    if t.startswith(("表 ", "图 ")) and len(t) < 60 and "　" in t:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Pt(0)
        for r in p.runs:
            r.font.size = Pt(10.5)
            r.font.bold = True
    if t.startswith(("关键词", "**关键词")):
        p.paragraph_format.first_line_indent = Pt(0)

for tbl in doc.tables:
    for row in tbl.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.first_line_indent = Pt(0)
                p.paragraph_format.line_spacing = 1.2
                for r in p.runs:
                    r.font.size = Pt(10.5)

for sec in doc.sections:
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.54)
    sec.left_margin = sec.right_margin = Cm(3.0)

doc.save(OUT)
print(f"wrote {OUT.relative_to(ROOT)}")
