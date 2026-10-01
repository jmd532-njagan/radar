-- Project memory: short facts about a project (environment, schedules, dependencies, contacts,
-- rules, quirks) that are always included in the agent's system prompt. Facts a person writes
-- are active at once; facts the agent (or, later, SOP extraction) proposes wait for approval.
-- Change history goes to audit_log.
CREATE TABLE "project_memory" (
    "id"          BIGSERIAL PRIMARY KEY,
    "project"     TEXT NOT NULL REFERENCES "project_metadata" ("project"),
    "kind"        TEXT NOT NULL,
    "text"        TEXT NOT NULL,
    "origin"      TEXT NOT NULL,
    "status"      TEXT NOT NULL DEFAULT 'proposed',
    "created_by"  UUID,
    "approved_by" UUID,
    "approved_at" TIMESTAMPTZ,
    "created_at"  TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at"  TIMESTAMPTZ
);
CREATE INDEX "ix_project_memory_project_status" ON "project_memory" ("project", "status");

-- The agent's fact-proposal tool is approval-gated like propose_failure_pattern.
INSERT INTO "rbac_permissions" ("tool_name", "allowed", "requires_consent", "platform")
VALUES ('propose_memory', true, true, 'radar')
ON CONFLICT ("tool_name") DO NOTHING;
