-- Chunk pipeline names only fed a search boost, removed after the SOP eval showed it hurt.
ALTER TABLE "sop_chunks" DROP COLUMN "pipelines";
