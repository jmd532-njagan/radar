"""
The tools a chat turn gets: the project-memory tools (llm/memory/tools.py) and SOP search
(llm/sop/tools.py) for every project, plus the tool set of the project's data platform. Only
"adf" has one today (platform_tools/adf/); a project on any other platform still gets a chat,
just without platform tools. Adding a platform means adding its branch below.
"""

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from llm.investigation_state import InvestigationState
from llm.memory.tools import build_memory_tools
from llm.sop.tools import build_sop_tools
from platform_tools.adf.tool_search_tool import build_chat_tools

logger = logging.getLogger(__name__)


async def build_tools_for_platform(
    platform: str,
    state: InvestigationState,
    db_factory: async_sessionmaker,
    message: str,
    user_id: str | None,
) -> list:
    tools = [
        *await build_memory_tools(state, db_factory, user_id),
        *build_sop_tools(state, db_factory),
    ]
    if platform == "adf":
        tools += await build_chat_tools(state, db_factory, message, user_id)
    else:
        logger.warning(
            "No tool set registered for platform=%r — only the project-memory and SOP tools",
            platform,
        )
    return tools
