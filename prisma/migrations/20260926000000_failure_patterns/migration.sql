-- project_rca becomes failure_patterns: one row per *kind* of failure in a project, matched by a
-- parsed signature (intake/signature.py) instead of a raw error string, and holding compact,
-- AI-oriented knowledge. Occurrences live on failure_events (pattern_id), so counts are derived
-- rather than stored; change history goes to audit_log.

ALTER TABLE "project_rca" RENAME TO "failure_patterns";
ALTER TABLE "failure_patterns" RENAME CONSTRAINT "project_rca_pkey" TO "failure_patterns_pkey";
ALTER TABLE "failure_patterns" RENAME CONSTRAINT "project_rca_project_fkey" TO "failure_patterns_project_fkey";
ALTER SEQUENCE "project_rca_id_seq" RENAME TO "failure_patterns_id_seq";
DROP INDEX IF EXISTS "uq_project_rca_pipeline_project_signature";

ALTER TABLE "failure_patterns" RENAME COLUMN "error_signature" TO "identity";
ALTER TABLE "failure_patterns" RENAME COLUMN "error_category" TO "category";
ALTER TABLE "failure_patterns" RENAME COLUMN "root_cause" TO "cause";

ALTER TABLE "failure_patterns"
    ADD COLUMN "status"      TEXT NOT NULL DEFAULT 'proposed',
    ADD COLUMN "platform"    TEXT,
    ADD COLUMN "code"        TEXT,
    ADD COLUMN "error_type"  TEXT,
    ADD COLUMN "template"    TEXT,
    ADD COLUMN "fingerprint" TEXT,
    ADD COLUMN "keywords"    TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN "pipelines"   TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN "cause_tag"   TEXT,
    ADD COLUMN "verify_with" TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN "fix_actions" TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN "impact"      TEXT,
    ADD COLUMN "criticality" TEXT,
    ADD COLUMN "confidence"  TEXT NOT NULL DEFAULT 'low',
    ADD COLUMN "approved_by" UUID,
    ADD COLUMN "approved_at" TIMESTAMPTZ,
    ADD COLUMN "created_at"  TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE "failure_patterns"
SET "pipelines"   = ARRAY["pipeline_id"],
    "fix_actions" = CASE WHEN "fix_applied" IS NULL THEN '{}' ELSE ARRAY["fix_applied"] END,
    "created_at"  = COALESCE("updated_at", now());

ALTER TABLE "failure_patterns"
    DROP COLUMN "pipeline_id",
    DROP COLUMN "fix_applied",
    DROP COLUMN "failure_count",
    DROP COLUMN "last_failure_timestamp",
    ALTER COLUMN "identity" DROP NOT NULL,
    ALTER COLUMN "category" DROP NOT NULL;

-- One pattern per identity per project; symptom-only patterns (from SOPs) have no identity.
CREATE UNIQUE INDEX "uq_failure_patterns_project_identity" ON "failure_patterns" ("project", "identity");

-- Each failure records which pattern it matched (or created) and how.
ALTER TABLE "failure_events"
    ADD COLUMN "pattern_id" BIGINT,
    ADD COLUMN "matched_by" TEXT,
    ADD COLUMN "outcome"    TEXT,
    ADD COLUMN "signature"  JSONB,
    ADD CONSTRAINT "failure_events_pattern_id_fkey"
        FOREIGN KEY ("pattern_id") REFERENCES "failure_patterns" ("id") ON DELETE SET NULL;
CREATE INDEX "ix_failure_events_pattern" ON "failure_events" ("pattern_id");

-- The agent's proposal tool is approval-gated like any mutating tool: the resolve path re-checks
-- rbac_permissions for every pending tool, so it needs a row. platform 'radar' = RADAR's own
-- tools, not a data platform's.
INSERT INTO "rbac_permissions" ("tool_name", "allowed", "requires_consent", "platform")
VALUES ('propose_failure_pattern', true, true, 'radar')
ON CONFLICT ("tool_name") DO NOTHING;
