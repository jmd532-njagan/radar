import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# text[] in Postgres; JSON on sqlite (the test database), which has no array type.
StringList = ARRAY(String).with_variant(JSON(), "sqlite")
FloatList = ARRAY(Float).with_variant(JSON(), "sqlite")


class ProjectMetadata(Base):
    __tablename__ = "project_metadata"

    # WatchTower's own projectName, verbatim — the same key public."Credential" and
    # public."UserProjectAssignment" use, so every cross-schema lookup matches exactly.
    project: Mapped[str] = mapped_column(String, primary_key=True)

    # A project is always one platform (adf | synapse | databricks | fabric), even if it has
    # multiple factories/accounts on that platform. Set automatically at intake and on first
    # chat, from the project's WatchTower integration.
    platform: Mapped[str | None] = mapped_column(String)


class RBACPermission(Base):
    """
    Per-tool gate, no role dimension. `allowed` gates whether a tool can be called at all;
    `requires_consent` tiers whether the native chat UI shows an approve/deny dialog first.
    """

    __tablename__ = "rbac_permissions"

    # Keyed by (platform, tool_name): two platforms may each have e.g. a list_pipelines.
    # RADAR's own tools (propose_failure_pattern, propose_memory) use platform "radar".
    platform: Mapped[str] = mapped_column(
        String, primary_key=True, default="adf", server_default="adf"
    )
    tool_name: Mapped[str] = mapped_column(String, primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class SopDocument(Base):
    """An uploaded SOP (.docx). A new upload for a project replaces the previous one: its
    status becomes `replaced` and its chunks are deleted. `warnings` are the mismatches found at
    upload (file name vs project, pipelines the SOP names that RADAR doesn't monitor, ...)."""

    __tablename__ = "sop_documents"
    __table_args__ = (
        Index("ix_sop_documents_project_status", "project", "status"),
        # At most one active SOP per project.
        Index(
            "uq_sop_documents_one_active",
            "project",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        CheckConstraint(
            "status IN ('active', 'replaced')", name="ck_sop_documents_status"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project: Mapped[str] = mapped_column(
        String, ForeignKey("project_metadata.project"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    uploaded_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class SopChunk(Base):
    """One retrievable piece of an SOP: a section's text under its heading path, and its
    bge-base embedding (768 floats)."""

    __tablename__ = "sop_chunks"
    __table_args__ = (Index("ix_sop_chunks_document", "document_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sop_documents.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(FloatList, nullable=False)


class ProjectMemory(Base):
    """A short fact about a project, always included in the agent's system prompt. Facts a
    person writes are active at once; facts the agent (or SOP extraction) proposes stay
    `proposed` until someone approves them. created_by/approved_by reference public."User"
    (FKs in the migration). Changes are recorded in audit_log."""

    __tablename__ = "project_memory"
    __table_args__ = (
        Index("ix_project_memory_project_status", "project", "status"),
        CheckConstraint(
            "kind IN ('rule', 'environment', 'schedule', 'dependency', 'contact', "
            "'verify_after', 'quirk')",
            name="ck_project_memory_kind",
        ),
        CheckConstraint(
            "origin IN ('human', 'incident', 'sop')", name="ck_project_memory_origin"
        ),
        CheckConstraint(
            "status IN ('proposed', 'active', 'retired')",
            name="ck_project_memory_status",
        ),
        CheckConstraint(
            "length(text) BETWEEN 1 AND 300", name="ck_project_memory_text_length"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project: Mapped[str] = mapped_column(
        String, ForeignKey("project_metadata.project"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposed")
    created_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    approved_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_chunk_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sop_chunks.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class FailurePattern(Base):
    """One kind of failure in a project, and what's known about it — compact fields written for
    the agent. `identity` is the parsed signature's specific code or, for generic wrapper codes,
    its fingerprint (intake/signature.py); null for symptom-only patterns extracted from SOPs.
    cause / category / verify_with / fix_actions are empty until a diagnosis is approved.
    Occurrences are the failure_events rows pointing here, so counts and "last seen" are derived;
    approved_by references public."User" (FK in the migration); changes go to audit_log."""

    __tablename__ = "failure_patterns"
    __table_args__ = (
        UniqueConstraint(
            "project", "identity", name="uq_failure_patterns_project_identity"
        ),
        CheckConstraint(
            "status IN ('proposed', 'active', 'retired')",
            name="ck_failure_patterns_status",
        ),
        CheckConstraint(
            "length(cause) <= 200", name="ck_failure_patterns_cause_length"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project: Mapped[str] = mapped_column(
        String, ForeignKey("project_metadata.project"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposed")
    identity: Mapped[str | None] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[str | None] = mapped_column(String)
    error_type: Mapped[str | None] = mapped_column(String)
    template: Mapped[str | None] = mapped_column(Text)
    pipelines: Mapped[list[str]] = mapped_column(
        StringList, nullable=False, default=list
    )
    category: Mapped[str | None] = mapped_column(String)
    cause: Mapped[str | None] = mapped_column(Text)
    verify_with: Mapped[list[str]] = mapped_column(
        StringList, nullable=False, default=list
    )
    fix_actions: Mapped[list[str]] = mapped_column(
        StringList, nullable=False, default=list
    )
    approved_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_chunk_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sop_chunks.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class AuditLog(Base):
    """
    Append-only, immutable — every row is self-contained (pipeline_name/project/platform stay
    denormalized on purpose, not joined from FailureEvent, so a row's meaning never changes
    even if the parent record's data changes later).

    investigation_id is nullable — an ad-hoc chat thread has no FailureEvent to point at, but
    its tool calls still need auditing. Postgres skips FK enforcement on NULL. thread_id is
    the only column that ties a row to the specific chat the tool call happened in —
    investigation_id alone doesn't cover it, since it's NULL for every ad-hoc thread, which is
    most chat usage. Also nullable — some events (chat/notification.py's "notification_ready") aren't
    chat-turn-scoped at all.

    user_id is WatchTower's public."User".id, the same real identity
    ChatThread.claimed_by_user_id uses — never an email, and never used for authorization here
    either, purely for "who did this" when reading the log. Nullable: system-originated events
    (intake, the diagnosis pipeline) have no real user to attribute to.
    """

    __tablename__ = "audit_log"

    audit_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    investigation_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("failure_events.investigation_id"), nullable=True, index=True
    )
    thread_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("chat_threads.thread_id"),
        nullable=True,
        index=True,
    )
    pipeline_name: Mapped[str] = mapped_column(String, nullable=False)
    project: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    detail: Mapped[dict | None] = mapped_column(JSON)


class FailureEvent(Base):
    """
    A row here is created the moment WatchTower posts a pipeline-failure event, whether or
    not a human ever opens it. investigation_id is the join key threaded through
    chat_threads/audit_log/notifications/workflow state everywhere else, and names that
    investigation's identity once a chat does start.
    """

    __tablename__ = "failure_events"
    __table_args__ = (
        CheckConstraint(
            "matched_by IN ('code', 'fingerprint', 'new')",
            name="ck_failure_events_matched_by",
        ),
        CheckConstraint(
            "outcome IN ('fixed', 'not_fixed', 'unknown')",
            name="ck_failure_events_outcome",
        ),
        Index(
            "ix_failure_events_project_pipeline_created",
            "project",
            "pipeline_name",
            "created_at",
        ),
    )

    # Durable record of "a failure came in", independent of whether anyone ever engages with
    # it. Intake writes this row immediately; run_diagnosis(investigation_id) is invoked later
    # (on a live "Diagnose" click), not automatically at intake.
    investigation_id: Mapped[str] = mapped_column(String, primary_key=True)
    # No standalone index — ix_failure_events_project_pipeline_created above already covers
    # plain project-only queries via the leftmost-prefix rule.
    project: Mapped[str] = mapped_column(
        String, ForeignKey("project_metadata.project"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String, nullable=False)
    pipeline_name: Mapped[str] = mapped_column(String, nullable=False)
    # The ADF factory the project's WatchTower integration pointed at when the failure came in.
    factory_name: Mapped[str | None] = mapped_column(String)
    run_status: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[dict | None] = mapped_column(JSON)
    trigger_type: Mapped[str | None] = mapped_column(String)
    # Written once at intake (chat/notification.py), read by the notification bell and the
    # draft ("new") chat page. The notification is resolved once a ChatThread with this
    # investigation_id exists (chat_threads.investigation_id is the only link between them).
    seed_message: Mapped[str | None] = mapped_column(Text)
    # Distinct from being resolved: sending a message resolves a notification, but a
    # human can open/read one from the notification list without ever sending anything. Set
    # the moment that specific notification's row is clicked in the list (not just when the
    # list itself is opened) — drives the "new" vs "already looked at this" opacity
    # distinction. NULL means nobody's opened it yet.
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The failure pattern this event matched or created, how it matched
    # (code | fingerprint | new), how the investigation ended, and the parsed signature.
    pattern_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("failure_patterns.id", ondelete="SET NULL"), index=True
    )
    matched_by: Mapped[str | None] = mapped_column(String)
    outcome: Mapped[str | None] = mapped_column(String)
    signature: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatThread(Base):
    """
    Not 1:1 with FailureEvent — a thread can be ad-hoc (project-scoped, no failure event) or
    failure-triggered (investigation_id set). A new ad-hoc thread ties to a project by the
    caller supplying `project` explicitly at creation (e.g. picked from the sidebar of
    projects the user has access to per WatchTower's UserProjectAssignment) — there's no
    other signal to infer it from. A failure-triggered thread instead inherits `project` from
    its FailureEvent row, so that association is automatic. claimed_by_user_id is set via a
    single atomic conditional UPDATE on first real write action (not on merely opening the
    thread), the standard optimistic-concurrency "claim" pattern.

    context_summary/summarized_through_timestamp back LLM context-window management — LLM-
    input-only, never a substitute for the real chat_messages transcript. summarized_through_
    timestamp is deliberately a plain timestamp, not a FK to a specific chat_messages.id:
    summarization only ever needs "give me messages after X," not a specific row's identity.

    pending_tool_approval is distinct from `status` — `status` stays scoped to the separate
    rerun-consent lifecycle (open -> awaiting_approval -> resolved); this column instead
    pauses one in-flight chat turn whose agent run hit a tool needing human approval (OpenAI
    Agents SDK's needs_approval mechanism). Shape: {"run_state": <RunState.to_json() output>,
    "pending_tools": [{"tool_call_id", "tool_name", "tool_arguments"}, ...],
    "triggering_message": <the user message this paused turn was built against - the resume
    path must rebuild the identical Agent/tool subset>, "created_at": <iso timestamp, for the
    90-minute TTL check>, "sdk_version": <installed openai-agents version, so a stale approval
    + upgraded SDK fails loud instead of deserializing into garbage>}. Nullable; null means no
    turn is currently paused.
    """

    __tablename__ = "chat_threads"

    # Python-side default (not server_default) so it works identically on both the real Postgres
    # column (which also has its own DEFAULT gen_random_uuid() from the migration — never
    # triggered since SQLAlchemy always supplies an explicit value) and the sqlite test fixture,
    # which has no gen_random_uuid() function at all.
    thread_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project: Mapped[str] = mapped_column(
        String, ForeignKey("project_metadata.project"), nullable=False, index=True
    )
    investigation_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("failure_events.investigation_id"), unique=True
    )
    # Auto-set from the first user message (plain truncation, see chat/service.py's
    # post_message), renamable via PATCH /chat/threads/{id}.
    title: Mapped[str | None] = mapped_column(String)
    # Real identity, WatchTower's public.User.id (a true cross-schema FK, see the migration) —
    # carried directly in the verified X-Radar-Assertion JWT's `id` claim (chat/access.py's
    # get_current_user_id).
    claimed_by_user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), index=True
    )
    # Soft delete: DELETE /chat/threads/{id} sets this instead of removing the row, so
    # nothing is ever actually lost. Every read path (_get_thread_or_404) excludes
    # is_deleted=true threads.
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    context_summary: Mapped[str | None] = mapped_column(Text)
    summarized_through_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    pending_tool_approval: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    """
    Append-only, full-fidelity, forever — the sole source of truth for both UI scrollback
    (cursor-paginated) and any context-summarization pass's input. Never rewritten.

    role is CHECK-constrained to user/assistant only — tool calls made while producing an
    assistant reply are summarized into that same row's tool_calls JSON column instead of
    becoming their own rows.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        # Serves cursor-paginated scrollback (WHERE thread_id = ? ORDER BY created_at) and
        # plain thread_id-only lookups (leftmost prefix).
        Index("ix_chat_messages_thread_created", "thread_id", "created_at"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("chat_threads.thread_id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ChatAnalytics(Base):
    """One row per LLM call (llm/client.py::add_usage): real token usage from the response,
    not the char-based estimate _message_out uses for the UI's live token_count display, plus
    an estimated cost. `purpose` says which call: a whole chat turn (summed across its
    responses), SOP extraction, the memory planner, a conversation summary or a thread title.
    user_id is who caused it; thread_id is null for calls outside a thread. Every row is
    self-contained (project/platform/model denormalized), same as AuditLog.
    """

    __tablename__ = "chat_analytics"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('chat', 'sop_extraction', 'memory_plan', 'summary', 'title')",
            name="ck_chat_analytics_purpose",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    thread_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("chat_threads.thread_id"), index=True
    )
    purpose: Mapped[str] = mapped_column(
        String, nullable=False, default="chat", server_default="chat"
    )
    user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), index=True)
    project: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # How many of input_tokens Azure served from its own prompt cache (a repeated identical
    # prefix, e.g. this turn's system prompt + tool schemas across its own multi-step
    # tool-calling loop, is billed at a discount automatically). A subset of input_tokens, not
    # a separate pool. estimated_cost prices it at the cheaper rate.
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MessageFeedback(Base):
    """Thumbs up/down on a specific assistant message. One row per (message_id, user_id): a
    second click from the same user overwrites their prior rating rather than accumulating
    duplicate rows, matching the frontend's own toggle-off-the-other/toggle-off-itself
    interaction.
    """

    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "user_id", name="uq_message_feedback_message_user"
        ),
        CheckConstraint("rating IN ('up', 'down')", name="ck_message_feedback_rating"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat_messages.id"), nullable=False
    )
    # FK to public."User" (in the migration; cross-schema, not modelled here).
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    rating: Mapped[str] = mapped_column(String, nullable=False)  # up | down
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
