"""llm/sop/parser.py on small synthetic .docx files."""

import asyncio
import io
import zipfile
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from llm.sop.parser import parse

_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(
    text: str, style: str | None = None, bold: bool = False, listed: bool = False
) -> str:
    ppr = ""
    if style or listed:
        ppr = "<w:pPr>"
        ppr += f'<w:pStyle w:val="{style}"/>' if style else ""
        ppr += '<w:numPr><w:numId w:val="1"/></w:numPr>' if listed else ""
        ppr += "</w:pPr>"
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f"<w:p>{ppr}<w:r>{rpr}<w:t>{text}</w:t></w:r></w:p>"


def _table(rows: list[list[str]]) -> str:
    cells = "".join(
        "<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in row) + "</w:tr>"
        for row in rows
    )
    return f"<w:tbl>{cells}</w:tbl>"


def _docx(*blocks: str) -> bytes:
    xml = f'<?xml version="1.0"?><w:document {_NS}><w:body>{"".join(blocks)}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_heading_styles_template_lines_and_tables():
    parsed = parse(
        _docx(
            _p("Standard Operating Procedure BDC_002", bold=True),
            _p("Setup", "Heading1"),
            _p("Explain:", "Heading3"),  # template prompt: dropped, not a path level
            _p("Pre-Checks", "Heading3"),
            _p("Input files availability", listed=True),
            # A sibling of Pre-Checks, though the levels skip H2.
            _p("Execution Steps", "Heading3"),
            _p("Example:"),
            _p("Trigger PL_Governance"),
            _table(
                [
                    ["Pipeline", "Trigger", "Owner"],
                    ["PL_Sales", "TRG_DAILY", "To be confirmed"],
                    # Only its label is left once placeholders go: dropped.
                    ["PL_Empty", "To be confirmed", "TBC"],
                ]
            ),
        )
    )
    assert parsed.cover == "Standard Operating Procedure BDC_002"
    assert [(c.heading_path, c.text) for c in parsed.chunks] == [
        ("Setup > Pre-Checks", "- Input files availability"),
        (
            "Setup > Execution Steps",
            "Trigger PL_Governance\nPipeline: PL_Sales; Trigger: TRG_DAILY",
        ),
    ]


def test_numbered_bold_titles_when_no_heading_styles():
    parsed = parse(
        _docx(
            _p("Table of Contents", bold=True),
            # The table of contents' entry: an empty section.
            _p("1. Client Overview", bold=True),
            _p("1. Client Overview", bold=True),
            _p("Shaw Gibbs is an accounting firm."),
            _p("1.1 Business context", bold=True),
            _p("• MDM identifies duplicate records."),
            _p("2. Tools", bold=True),
            _p("3 pipelines run nightly."),  # numbered but not bold: body text
        )
    )
    assert [(c.heading_path, c.text) for c in parsed.chunks] == [
        ("Client Overview", "Shaw Gibbs is an accounting firm."),
        ("Client Overview > Business context", "MDM identifies duplicate records."),
        ("Tools", "3 pipelines run nightly."),
    ]


def test_long_section_splits_at_line_boundaries():
    lines = [_p(" ".join(["word"] * 60)) for _ in range(5)]
    parsed = parse(_docx(_p("Steps", "Heading1"), *lines))
    assert len(parsed.chunks) == 2
    assert all(c.heading_path == "Steps" for c in parsed.chunks)


def test_not_a_docx():
    with pytest.raises(ValueError):
        parse(b"not a zip")


def test_failure_start_sop_sections_need_the_pipeline_named():
    from types import SimpleNamespace

    from llm.sop import search

    rows = [
        SimpleNamespace(
            heading_path="RCA > SFTP",
            text="PL_Investment_Metrics_Ingestion fails when the SFTP file is late.",
            embedding=[1.0, 0.0],
        ),
        SimpleNamespace(
            heading_path="Contacts", text="Escalate to the EM.", embedding=[0.0, 1.0]
        ),
    ]
    index = search.build_index(1, rows)

    async def run(term):
        with (
            patch.object(search, "_index", AsyncMock(return_value=index)),
            patch.object(
                search,
                "embed_texts_async",
                AsyncMock(return_value=np.array([[1.0, 0.0]], dtype=np.float32)),
            ),
        ):
            return await search.search(
                None, "p", "sftp file missing", k=3, must_mention=term
            )

    assert [h["section"] for h in asyncio.run(run("pl_investment_metrics_ingestion"))][
        0
    ] == "RCA > SFTP"
    assert asyncio.run(run("pl_unrelated_pipeline")) == []
