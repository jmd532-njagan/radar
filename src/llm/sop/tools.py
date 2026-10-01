"""
search_sop — the agent's on-demand lookup into the project's SOP (search.py). Read-only and
project-scoped, so no approval and no RBAC gateway, like get_failure_patterns.
"""

import json

from agents import function_tool
from sqlalchemy.ext.asyncio import async_sessionmaker

from llm.injection_detection import drop_flagged
from llm.investigation_state import InvestigationState
from llm.sop.search import search


def build_sop_tools(state: InvestigationState, db_factory: async_sessionmaker) -> list:
    async def search_sop(query: str) -> str:
        """Search this project's SOP (its standard operating procedure document) for how the
        project is run: pipelines and what they load, schedules and triggers, manual steps,
        environments and branching, who to contact, checks after a run, and past incidents.
        Returns the most relevant sections; cite the section when you use one. The SOP can be
        out of date — confirm anything about current state with a live tool.

        Args:
            query: what you want to know, in plain words; name the pipeline if the question
                is about one.
        """
        async with db_factory() as db:
            hits = await search(db, state["project"], query)
        if not hits:
            return json.dumps("This project has no SOP uploaded.")
        return json.dumps(await drop_flagged(hits, source="search_sop"))

    return [function_tool(search_sop)]
