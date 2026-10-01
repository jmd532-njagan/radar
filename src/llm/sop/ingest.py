"""
SOP upload: .docx → chunks + proposals, replacing the project's previous SOP.

1. Parse into chunks (parser.py) and embed them (bge-base).
2. One LLM pass over the numbered chunks proposes what should become project knowledge:
   lasting facts (→ project_memory, origin `sop`) and the RCA table's issues (→ symptom-only
   failure_patterns, no identity: they match nothing at intake but show up in search and the
   Project Memory panel). Facts go straight into memory (the uploader is a project member
   vouching for the SOP); issues are `proposed` patterns a member approves in the panel. Both
   link back to their source chunk.
3. Consistency warnings, stored on the document: file name vs project, the SOP's pipelines vs
   the pipelines the project's integration monitors, and the SOP's project code vs JIN's.

Steps 1-2 run before any write, so a slow model call never holds a transaction open.
"""

import hashlib
import json
import logging
import re
from pathlib import PurePath

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import SOP_MAX_FACTS, settings
from db import project_memory, sop
from db.models import FailurePattern, ProjectMetadata, SopChunk, SopDocument
from db.projects import ensure_project_metadata
from llm.client import add_usage, azure_client
from llm.embeddings import embed_texts_async
from llm.sop.parser import Chunk, parse
from llm.sop.search import passage

logger = logging.getLogger(__name__)

_PIPELINE_ID = re.compile(r"\b(?:PL|TRG)_\w+")
_PROJECT_CODE = re.compile(
    r"\b[A-Z]{2,5}_\d{3}\b"
)  # JIN project codes: BDC_002, STR_005

_EXTRACTION_PROMPT = f"""You read a data project's Standard Operating Procedure (SOP) and pick out
what an on-call engineer investigating a pipeline failure needs to remember about the project.
The SOP is given as numbered chunks: "[n] section path" followed by its text.

Return JSON with exactly these keys:
{{
  "facts": [{{"chunk": n, "kind": "...", "text": "..."}}],
  "issues": [{{"chunk": n, "symptom": "...", "cause": "...", "fix": "..."}}],
  "pipelines": ["..."]
}}

facts: only facts that would change what an engineer does or checks when this project's
pipeline fails. Fewer is better; most SOPs need 10-25, hard limit {SOP_MAX_FACTS}. One short
self-contained sentence each (under 250 characters), naming the pipeline/system/person it's
about. Use the SOP's own words: don't expand an abbreviation it doesn't expand (write "EM", not
a guess at what EM stands for), and don't state the same thing twice. chunk is the [n] of the chunk holding the fact's details (the table row, time, name),
not the section introducing it.
Cover these first, whenever the SOP has them:
1. every named person with their role (developers, leads, managers, client contacts, who grants
   access): one contact fact per role group, with emails when given;
2. which trigger runs which pipelines, and which master pipeline runs which child pipelines;
3. schedules with their days, times and timezone, and how long runs take;
4. manual steps and pre-run checks with the exact names involved (pipeline, schema, table,
   file, folder, connector), e.g. a pipeline setting to change before triggering it, or
   "confirm every Fivetran sync completed";
5. where secrets and credentials live, and which environment is really live;
6. incident SLAs and escalation rules.
kind is one of:
- rule: a process rule that must be followed (branching, approvals, what not to do)
- environment: environments, where things run, storage/database locations
- schedule: when pipelines/triggers/refreshes run and how long they take
- dependency: upstream sources and what feeds what
- contact: who to escalate to or ask, with their role
- verify_after: a concrete check (table, row count, dashboard, status) after a run or fix;
  not a description of data flow
- quirk: a non-obvious manual step or gotcha
Skip company background, generic best practice, and anything marked as a placeholder. Also
skip what a tool is generally used for ("Power BI is used for reports"), a pipeline's name
restated as its purpose, QA/SLA wording that would fit any project, and anything inferable from
a pipeline's name. Skip validation checklists (row counts, nulls, schema checks, "outputs are
ready") unless they name a specific table, metric or dashboard. Don't restate the incident/RCA
table as facts; that is what issues are for. Merge facts that differ in one value into one
sentence (e.g. all dashboard refresh cadences). When the SOP contradicts itself, write one fact
giving both values and where each is stated, e.g. "Venture refresh: monthly per Deliverables,
quarterly per SLAs".

issues: one per row of the SOP's incident / RCA / common-issues table that has a real root
cause. symptom = what is observed (one sentence), cause under 180 characters, fix = what was
done. Leave the list empty if the SOP has no such table.

pipelines: every pipeline and trigger identifier the SOP names (e.g. PL_..., TRG_...,
Master_..._Reporting), spelled exactly as written, without a trailing word "pipeline". Not
layer, stage or process names such as Ingestion or MDM, and not source-system, database or
connection identifiers (e.g. sg_cch, a Fivetran connector name).
"""


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _monitored_pipelines(db: AsyncSession, project: str) -> list[str]:
    result = await db.execute(
        text(
            'SELECT pipelines FROM public."Credential" '
            'WHERE "projectName" = :project AND NOT "isDeleted"'
        ),
        {"project": project},
    )
    return sorted({p for (pipelines,) in result for p in pipelines or [] if p})


async def _jin_project_code(db: AsyncSession, project: str) -> str | None:
    return await db.scalar(
        text(
            'SELECT project_code FROM public."AppProject" WHERE project_name = :project'
        ),
        {"project": project},
    )


async def _extract(chunks: list[Chunk]):
    """The extraction JSON, and the call's usage."""
    numbered = "\n\n".join(
        f"[{i}] {c.heading_path}\n{c.text}" for i, c in enumerate(chunks)
    )
    response = await azure_client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": _EXTRACTION_PROMPT},
            {"role": "user", "content": numbered},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content or "{}"), response.usage


def _warnings(
    project: str,
    file_name: str,
    cover: str,
    sop_pipelines: list[str],
    monitored: list[str],
    jin_code: str | None,
) -> list[str]:
    warnings = []
    if PurePath(file_name).stem.strip().casefold() != project.strip().casefold():
        warnings.append(
            f'The file is named "{file_name}", not after the project "{project}". '
            "Check it's the right project's SOP."
        )
    known = {p.casefold() for p in monitored}
    unmonitored = [p for p in sop_pipelines if p.casefold() not in known]
    if unmonitored:
        warnings.append(
            "The SOP mentions pipelines RADAR doesn't monitor for this project: "
            + ", ".join(unmonitored)
        )
    mentioned = {p.casefold() for p in sop_pipelines}
    missing = [p for p in monitored if p.casefold() not in mentioned]
    if missing:
        warnings.append(
            "Monitored pipelines the SOP doesn't mention: " + ", ".join(missing)
        )
    codes = set(_PROJECT_CODE.findall(cover))
    if jin_code and codes and jin_code not in codes:
        warnings.append(
            f"The SOP is for {', '.join(sorted(codes))}, but this project's code is {jin_code}."
        )
    return warnings


async def ingest(
    db: AsyncSession, project: str, file_name: str, data: bytes, user_id: str
) -> SopDocument:
    """Stores the SOP as the project's active one, with its chunks and proposals. Does not
    commit. Raises ValueError for a file that isn't a usable SOP."""
    parsed = parse(data)
    if not parsed.chunks:
        raise ValueError("No sections found in this document")
    monitored = await _monitored_pipelines(db, project)
    vectors = await embed_texts_async(
        [passage(c.heading_path, c.text) for c in parsed.chunks]
    )
    extracted, usage = await _extract(parsed.chunks)

    # The model misses some names (trigger tables especially); PL_/TRG_ identifiers in the
    # text are found directly and added, keeping the first spelling of each.
    found = _PIPELINE_ID.findall(" ".join(c.text for c in parsed.chunks))
    sop_pipelines = list(
        {
            p.casefold(): p
            for p in [*extracted.get("pipelines", []), *found]
            if isinstance(p, str) and p
        }.values()
    )
    names = {p.casefold(): p for p in [*monitored, *sop_pipelines]}
    platform = await db.scalar(
        select(ProjectMetadata.platform).where(ProjectMetadata.project == project)
    )
    if platform is None:
        platform = "adf"  # same default as a new ad-hoc chat (chat/service.py)
        await ensure_project_metadata(db, project, platform)
    add_usage(
        db,
        usage,
        purpose="sop_extraction",
        project=project,
        platform=platform,
        user_id=user_id,
    )

    version = await sop.replace_active(db, project)
    document = SopDocument(
        project=project,
        file_name=file_name,
        content_hash=content_hash(data),
        version=version,
        warnings=_warnings(
            project,
            file_name,
            parsed.cover,
            sop_pipelines,
            monitored,
            await _jin_project_code(db, project),
        ),
        uploaded_by=user_id,
    )
    db.add(document)
    await db.flush()
    rows = [
        SopChunk(
            document_id=document.id,
            position=i,
            heading_path=c.heading_path,
            text=c.text,
            embedding=vector.tolist(),
        )
        for i, (c, vector) in enumerate(zip(parsed.chunks, vectors, strict=True))
    ]
    db.add_all(rows)
    await db.flush()

    def source(item: dict) -> int | None:
        n = item.get("chunk")
        return rows[n].id if isinstance(n, int) and 0 <= n < len(rows) else None

    for item in extracted.get("facts", [])[:SOP_MAX_FACTS]:
        fact_text = str(item.get("text", "")).strip()
        if item.get("kind") in project_memory.KINDS and 0 < len(fact_text) <= 300:
            fact = project_memory.create(
                db, project, item["kind"], fact_text, "sop", user_id
            )
            fact.source_chunk_id = source(item)
    for item in extracted.get("issues", []):
        symptom, cause = (
            str(item.get("symptom", "")).strip(),
            str(item.get("cause", "")).strip(),
        )
        if symptom and 0 < len(cause) <= 200:
            db.add(
                FailurePattern(
                    project=project,
                    status="proposed",
                    platform=platform,
                    template=symptom,
                    pipelines=[
                        orig for key, orig in names.items() if key in symptom.casefold()
                    ],
                    cause=cause,
                    fix_actions=[f] if (f := str(item.get("fix", "")).strip()) else [],
                    source_chunk_id=source(item),
                )
            )
    await db.flush()
    logger.info(
        "SOP v%s for %s: %s chunks, %s warnings",
        version,
        project,
        len(rows),
        len(document.warnings),
    )
    return document
