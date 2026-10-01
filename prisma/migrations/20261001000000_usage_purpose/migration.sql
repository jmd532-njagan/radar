-- chat_analytics records every LLM call, not only chat turns: `purpose` says which kind, and
-- thread_id is null for calls outside a thread (SOP extraction, the memory planner).
ALTER TABLE radar."chat_analytics"
  ADD COLUMN "purpose" TEXT NOT NULL DEFAULT 'chat',
  ADD CONSTRAINT "ck_chat_analytics_purpose"
    CHECK ("purpose" IN ('chat', 'sop_extraction', 'memory_plan', 'summary', 'title')),
  ALTER COLUMN "thread_id" DROP NOT NULL;
