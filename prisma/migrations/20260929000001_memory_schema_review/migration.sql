-- Review of the memory tables: drop columns that were redundant or unused, and let the database
-- enforce allowed values, length limits and user references (same conventions as the rest of the
-- schema: CHECKs on enum-like columns, cross-schema FKs to public."User" with ON DELETE SET NULL).

-- failure_patterns: fingerprint lives in identity; keywords derive from code + template;
-- confidence mirrored status; cause_tag overlapped category + cause; impact/criticality come
-- back with SOP extraction if needed. The category guessed at intake was right 4% of the time,
-- so category stays empty until a diagnosis is approved.
ALTER TABLE "failure_patterns"
    DROP COLUMN "fingerprint",
    DROP COLUMN "keywords",
    DROP COLUMN "confidence",
    DROP COLUMN "cause_tag",
    DROP COLUMN "impact",
    DROP COLUMN "criticality";
UPDATE "failure_patterns" SET "category" = NULL WHERE "category" = 'unknown' AND "status" <> 'active';
UPDATE "failure_patterns" SET "updated_at" = COALESCE("updated_at", "created_at");
UPDATE "failure_patterns" SET "platform" = COALESCE("platform", 'adf');
ALTER TABLE "failure_patterns"
    ALTER COLUMN "platform" SET NOT NULL,
    ALTER COLUMN "updated_at" SET NOT NULL,
    ALTER COLUMN "updated_at" SET DEFAULT now(),
    ADD CONSTRAINT "ck_failure_patterns_status" CHECK ("status" IN ('proposed', 'active', 'retired')),
    ADD CONSTRAINT "ck_failure_patterns_cause_length" CHECK (char_length("cause") <= 200),
    ADD CONSTRAINT "failure_patterns_approved_by_fkey"
        FOREIGN KEY ("approved_by") REFERENCES public."User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- failure_events: the occurrence columns only take known values.
ALTER TABLE "failure_events"
    ADD CONSTRAINT "ck_failure_events_matched_by" CHECK ("matched_by" IN ('code', 'fingerprint', 'new')),
    ADD CONSTRAINT "ck_failure_events_outcome" CHECK ("outcome" IN ('fixed', 'not_fixed', 'unknown'));

-- project_memory: known kinds/origins/statuses, short text (it's in every prompt), real users.
UPDATE "project_memory" SET "updated_at" = COALESCE("updated_at", "created_at");
ALTER TABLE "project_memory"
    ALTER COLUMN "updated_at" SET NOT NULL,
    ALTER COLUMN "updated_at" SET DEFAULT now(),
    ADD CONSTRAINT "ck_project_memory_kind" CHECK ("kind" IN ('rule', 'environment', 'schedule', 'dependency', 'contact', 'verify_after', 'quirk')),
    ADD CONSTRAINT "ck_project_memory_origin" CHECK ("origin" IN ('human', 'incident', 'sop')),
    ADD CONSTRAINT "ck_project_memory_status" CHECK ("status" IN ('proposed', 'active', 'retired')),
    ADD CONSTRAINT "ck_project_memory_text_length" CHECK (char_length("text") BETWEEN 1 AND 300),
    ADD CONSTRAINT "project_memory_created_by_fkey"
        FOREIGN KEY ("created_by") REFERENCES public."User"("id") ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT "project_memory_approved_by_fkey"
        FOREIGN KEY ("approved_by") REFERENCES public."User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
