"""
SOP .docx → retrievable chunks.

Reads word/document.xml straight from the zip with defusedxml (no python-docx). The body is
split into sections by heading path: Word heading styles when the document uses them, otherwise
short bold numbered titles ("6.3 Master data management") — some SOPs are formatted by hand.
Everything before the first heading (cover page, table of contents) is dropped, as are the JMAN
SOP template's own instruction lines ("Clearly define:", "Example:") and placeholder cells
("To be confirmed"). Table rows are flattened to "Header: value; Header: value" so each row
stands on its own for both keyword and embedding search. A section longer than SOP_CHUNK_WORDS
is split at line boundaries.
"""

import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from config.settings import SOP_CHUNK_WORDS

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEADING_STYLE = re.compile(r"^Heading(\d)$")
_NUMBERED_TITLE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\D.{0,80})$")
_HEADING_NOTE = re.compile(r"\s*\(if [^)]*\)")  # "Data QA (if data project)"


def _norm(line: str) -> str:
    line = line.replace("’", "'").replace("“", '"').replace("”", '"')
    return " ".join(line.lower().split()).strip(' :."')


# The JMAN SOP template's instructions and examples, left in by whoever filled it in.
_TEMPLATE_LINES = {
    _norm(line)
    for line in (
        "A brief introduction to the client:",
        "Summarise your team's role and deliverables:",
        "Clearly define:",
        "List all applications, platforms, and technologies required:",
        "Provide a clear overview of all environments involved in the project:",
        "Explain:",
        "Explain how code changes move across environments:",
        "For Data Projects",
        "This section helps new team members understand major building blocks.",
        "This is the main procedural section.",
        "Before running any job/process, validate:",
        "List outcomes expected after successful execution, that need to be verified:",
        "Example:",
        "Updated tables or dashboards",
        "API returning correct status",
        "UI components rendering correctly",
        "Files generated and stored in correct location",
        "What QA or operator must check before approving the run:",
        "This could be subject to project",
        'Clear criteria for "Run is successful" or "Release is approved."',
        "Define operational expectations:",
        "Provide all supporting materials and other documentations:",
        "Supporting materials and other documentations:",
        "A section to maintain historical learnings and preventive actions.",
        "Data flow diagrams (if available)",
        "Key SQL tables (input, processed, output)",
    )
}
_PLACEHOLDERS = {"to be confirmed", "to be rated", "to be documented", "tbc", "n/a"}


@dataclass(frozen=True)
class Chunk:
    heading_path: str
    text: str


@dataclass(frozen=True)
class ParsedSop:
    cover: str  # text before the first heading: title, project code
    chunks: list[Chunk]


def _text(el: Element) -> str:
    return " ".join("".join(t.text or "" for t in el.iter(_W + "t")).split())


def _is_placeholder(cell: str) -> bool:
    cell = _norm(cell)
    return not cell or cell in _PLACEHOLDERS or cell.startswith("not specified")


def _table_lines(tbl: Element) -> list[str]:
    # A cell's paragraphs are joined with a space: one per pipeline name is common.
    rows = [
        [
            " ".join(filter(None, map(_text, c.findall(_W + "p"))))
            for c in tr.findall(_W + "tc")
        ]
        for tr in tbl.findall(_W + "tr")
    ]
    if len(rows) < 2:
        return [" | ".join(r) for r in rows if any(r)]
    header, lines = rows[0], []
    for row in rows[1:]:
        cells = [
            (h, c) for h, c in zip(header, row, strict=False) if not _is_placeholder(c)
        ]
        if len(cells) > 1:  # a row with only its label left says nothing
            lines.append("; ".join(f"{h}: {c}" if h else c for h, c in cells))
    return lines


def _paragraph(p: Element) -> tuple[str, str | None, bool, bool]:
    """(text, style, is_list_item, is_bold)."""
    ppr = p.find(_W + "pPr")
    style_el = ppr.find(_W + "pStyle") if ppr is not None else None
    style = style_el.get(_W + "val") if style_el is not None else None
    listed = (ppr is not None and ppr.find(_W + "numPr") is not None) or bool(
        style and ("Bullet" in style or "List" in style)
    )
    return _text(p), style, listed, p.find(f".//{_W}b") is not None


def _heading(
    text: str, style: str | None, bold: bool, styled_doc: bool
) -> tuple[int, str] | None:
    """(level, title) when the paragraph is a heading."""
    if styled_doc:
        match = _HEADING_STYLE.match(style or "")
        return (int(match.group(1)), text) if match else None
    match = _NUMBERED_TITLE.match(text)
    if not (match and bold):
        return None
    return len(match.group(1).split(".")), match.group(2)


def _split(path: list[tuple[int, str]], lines: list[str]) -> list[Chunk]:
    heading = " > ".join(title for _, title in path)
    chunks, current, words = [], [], 0
    for line in lines:
        n = len(line.split())
        if current and words + n > SOP_CHUNK_WORDS:
            chunks.append(Chunk(heading, "\n".join(current)))
            current, words = [], 0
        current.append(line)
        words += n
    if current:
        chunks.append(Chunk(heading, "\n".join(current)))
    return chunks


def parse(data: bytes) -> ParsedSop:
    """Raises ValueError when the bytes aren't a readable .docx."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            body = ElementTree.fromstring(z.read("word/document.xml")).find(_W + "body")
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ValueError("Not a readable .docx file") from exc
    if body is None:
        raise ValueError("Not a readable .docx file")

    styled_doc = any(
        _HEADING_STYLE.match(s.get(_W + "val") or "") for s in body.iter(_W + "pStyle")
    )
    cover, path, lines, chunks = [], None, [], []
    for el in body:
        if el.tag == _W + "tbl":
            if path is not None:
                lines += _table_lines(el)
            continue
        if el.tag != _W + "p":
            continue
        text, style, listed, bold = _paragraph(el)
        if not text or _norm(text) in _TEMPLATE_LINES:
            continue
        heading = _heading(text, style, bold, styled_doc)
        if heading is not None:
            if path is not None:
                chunks += _split(path, lines)
            level, title = heading
            # Levels can skip (Heading1 then Heading3): keep only strictly higher ancestors.
            title = _HEADING_NOTE.sub("", title)
            path = [*(h for h in path or [] if h[0] < level), (level, title)]
            lines = []
        elif path is None:
            cover.append(text)
        else:
            text = text.lstrip("•· ").strip()
            lines.append(f"- {text}" if listed else text)
    if path is not None:
        chunks += _split(path, lines)
    return ParsedSop(" ".join(cover), chunks)
