"""
Conversation compaction. After a turn, if the messages since the last summary exceed the token
budget, everything except the most recent messages is folded into ChatThread.context_summary
and the cursor (summarized_through_timestamp) moves past it. The next turn sends the summary as
system context (llm/agent.py) plus the recent messages word for word.
"""

import logging

import tiktoken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import (
    SUMMARY_KEEP_RAW_MESSAGES,
    SUMMARY_MAX_TOKENS,
    SUMMARY_TOKEN_BUDGET,
    settings,
)
from db.models import ChatMessage, ChatThread
from llm.client import add_usage, azure_client

logger = logging.getLogger(__name__)

_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


async def maybe_summarize(
    db: AsyncSession, thread: ChatThread, user_id: str | None, platform: str
) -> None:
    """Runs after the reply is persisted, so it never delays the reply itself. The call's
    usage is recorded against the user whose turn triggered it."""
    messages = list(
        (
            await db.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.thread_id == thread.thread_id,
                    ChatMessage.created_at
                    > (thread.summarized_through_timestamp or thread.created_at),
                )
                .order_by(ChatMessage.created_at)
            )
        ).scalars()
    )
    older = messages[:-SUMMARY_KEEP_RAW_MESSAGES]
    if not older:
        return
    transcript = "\n".join(f"{m.role}: {m.content}" for m in messages)
    if count_tokens(transcript) <= SUMMARY_TOKEN_BUDGET:
        return

    older_text = "\n".join(f"{m.role}: {m.content}" for m in older)
    prompt = (
        "Update the summary of this pipeline-failure conversation. Keep only what a "
        "continuation needs: pipeline names, error codes, findings, decisions, fixes tried and "
        "their results. At most 200 words.\n\n"
        f"Current summary:\n{thread.context_summary or '(none)'}\n\n"
        f"Messages to fold in:\n{older_text}"
    )
    try:
        response = await azure_client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=SUMMARY_MAX_TOKENS,
        )
    except Exception:
        logger.exception(
            "Summarization failed for thread_id=%s; keeping the current summary",
            thread.thread_id,
        )
        return

    thread.context_summary = response.choices[0].message.content
    add_usage(
        db,
        response.usage,
        purpose="summary",
        project=thread.project,
        platform=platform,
        user_id=user_id,
        thread_id=thread.thread_id,
    )
    thread.summarized_through_timestamp = older[-1].created_at
    await db.commit()
