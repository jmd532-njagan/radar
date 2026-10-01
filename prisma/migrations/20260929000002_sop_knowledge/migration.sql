-- SOP knowledge: each uploaded SOP (.docx) and the chunks it's split into for retrieval. A
-- project has tens to hundreds of chunks, so keyword and vector scoring run in memory
-- (mcp_servers/sop/search.py) — no full-text or vector index needed. Facts and failure
-- patterns extracted from an SOP point back to the chunk they came from.

CREATE TABLE "sop_documents" (
    "id"          BIGSERIAL PRIMARY KEY,
    "project"     TEXT NOT NULL REFERENCES "project_metadata" ("project"),
    "file_name"   TEXT NOT NULL,
    "content_hash" TEXT NOT NULL,
    "version"     INTEGER NOT NULL,
    "status"      TEXT NOT NULL DEFAULT 'active',
    "warnings"    JSONB NOT NULL DEFAULT '[]',
    "uploaded_by" UUID REFERENCES public."User" ("id") ON DELETE SET NULL ON UPDATE CASCADE,
    "uploaded_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT "ck_sop_documents_status" CHECK ("status" IN ('active', 'replaced'))
);
CREATE INDEX "ix_sop_documents_project_status" ON "sop_documents" ("project", "status");

CREATE TABLE "sop_chunks" (
    "id"           BIGSERIAL PRIMARY KEY,
    "document_id"  BIGINT NOT NULL REFERENCES "sop_documents" ("id") ON DELETE CASCADE,
    "project"      TEXT NOT NULL REFERENCES "project_metadata" ("project"),
    "position"     INTEGER NOT NULL,
    "heading_path" TEXT NOT NULL,
    "text"         TEXT NOT NULL,
    "pipelines"    TEXT[] NOT NULL DEFAULT '{}',
    "embedding"    REAL[] NOT NULL
);
CREATE INDEX "ix_sop_chunks_project" ON "sop_chunks" ("project");

ALTER TABLE "project_memory"
    ADD COLUMN "source_chunk_id" BIGINT REFERENCES "sop_chunks" ("id") ON DELETE SET NULL;
ALTER TABLE "failure_patterns"
    ADD COLUMN "source_chunk_id" BIGINT REFERENCES "sop_chunks" ("id") ON DELETE SET NULL;
