-- Schema review fixes (2026-09-30).

-- 1. sop_chunks: every SOP search load and every replace filters on document_id, which had no
--    index; the project copy on each chunk was never queried (the document has the project).
DROP INDEX IF EXISTS "ix_sop_chunks_project";
ALTER TABLE "sop_chunks" DROP COLUMN "project";
CREATE INDEX "ix_sop_chunks_document" ON "sop_chunks"("document_id");

-- 2. At most one active SOP per project, guaranteed by the database rather than only by the
--    upload code (two simultaneous uploads could otherwise both stay active).
CREATE UNIQUE INDEX "uq_sop_documents_one_active" ON "sop_documents"("project") WHERE "status" = 'active';

-- 3. message_feedback.user_id references a real WatchTower user, like every other user column.
DELETE FROM "message_feedback" f
WHERE NOT EXISTS (SELECT 1 FROM public."User" u WHERE u."id" = f."user_id");
ALTER TABLE "message_feedback"
  ADD CONSTRAINT "message_feedback_user_id_fkey" FOREIGN KEY ("user_id")
  REFERENCES public."User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- 4. The failure -> thread link was stored both ways; chat_threads.investigation_id (unique)
--    is kept. Carry over any link that only existed on the failure side, then drop it.
UPDATE "chat_threads" t
SET "investigation_id" = f."investigation_id"
FROM "failure_events" f
WHERE f."resolved_thread_id" = t."thread_id" AND t."investigation_id" IS NULL;
ALTER TABLE "failure_events" DROP COLUMN "resolved_thread_id";

-- 5. rbac_permissions is keyed by (platform, tool_name): a second platform may reuse a tool name.
ALTER TABLE "rbac_permissions"
  DROP CONSTRAINT "rbac_permissions_pkey",
  ADD CONSTRAINT "rbac_permissions_pkey" PRIMARY KEY ("platform", "tool_name");
