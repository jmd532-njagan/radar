"""
The one Azure OpenAI client (Azure AI Foundry's v1 endpoint): the Agents SDK's default for the
chat agent (set on import, process-wide), and used directly for conversation summaries, SOP
extraction and the memory planner. Also where every LLM call's usage is recorded (add_usage).
"""

import logging
from datetime import UTC, datetime

from agents import set_default_openai_client, set_tracing_disabled
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import (
    AZURE_OPENAI_MODEL,
    PRICE_PER_1M_CACHED_INPUT,
    PRICE_PER_1M_INPUT,
    PRICE_PER_1M_OUTPUT,
    settings,
)
from db.models import ChatAnalytics

logger = logging.getLogger(__name__)

azure_client = AsyncOpenAI(
    base_url=settings.azure_openai_v1_base_url,
    api_key=settings.azure_openai_api_key,
)

set_default_openai_client(azure_client, use_for_tracing=False)
set_tracing_disabled(True)  # no OpenAI platform account to receive Agents SDK traces


def estimate_cost(input_tokens: int, output_tokens: int, cached_tokens: int) -> float:
    return round(
        (
            (input_tokens - cached_tokens) * PRICE_PER_1M_INPUT
            + cached_tokens * PRICE_PER_1M_CACHED_INPUT
            + output_tokens * PRICE_PER_1M_OUTPUT
        )
        / 1_000_000,
        6,
    )


def add_usage(
    db: AsyncSession,
    usage,
    *,
    purpose: str,
    project: str,
    platform: str,
    user_id: str | None,
    thread_id: str | None = None,
) -> None:
    """Adds one chat_analytics row to the session (the caller commits). `usage` is a
    chat-completions response's usage (prompt_tokens, completion_tokens,
    prompt_tokens_details.cached_tokens) or, for an Agents SDK run, the token-count dict
    llm/agent.py's _usage sums. Unreadable usage is logged and skipped, so recording never
    fails the call it measures."""
    try:
        if isinstance(usage, dict):
            input_tokens = usage["input_tokens"]
            output_tokens = usage["output_tokens"]
            cached_tokens = usage["cached_tokens"]
        else:
            input_tokens = int(usage.prompt_tokens)
            output_tokens = int(usage.completion_tokens)
            details = usage.prompt_tokens_details
            cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)
    except Exception:
        logger.exception("Usage not recorded: purpose=%s project=%s", purpose, project)
        return
    db.add(
        ChatAnalytics(
            thread_id=thread_id,
            purpose=purpose,
            user_id=user_id,
            project=project,
            platform=platform,
            model=AZURE_OPENAI_MODEL,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            estimated_cost=estimate_cost(input_tokens, output_tokens, cached_tokens),
            created_at=datetime.now(UTC),
        )
    )
