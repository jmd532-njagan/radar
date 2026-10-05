-- What prisma/schema.prisma can't express (CHECKs, a partial index, foreign keys into
-- WatchTower's public schema, tool permissions), applied after the tables exist:
--   npx prisma migrate dev --name init                  (tables, from the schema)
--   npx prisma db execute --file prisma/seed.sql --schema prisma/schema.prisma
-- Safe to run again: existing constraints are skipped and existing rows are left as they are.
-- Keep it in step with db/models.py (CHECKs and the partial index) and the tool registries
-- (platform_tools/adf/tools, llm/memory/tools.py) when they change.

-- CHECK constraints (enum-like columns and length limits).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_chat_analytics_purpose') THEN
    ALTER TABLE radar.chat_analytics ADD CONSTRAINT ck_chat_analytics_purpose CHECK ((purpose = ANY (ARRAY['chat'::text, 'sop_extraction'::text, 'memory_plan'::text, 'summary'::text, 'title'::text])));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_chat_messages_role') THEN
    ALTER TABLE radar.chat_messages ADD CONSTRAINT ck_chat_messages_role CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text])));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_failure_events_matched_by') THEN
    ALTER TABLE radar.failure_events ADD CONSTRAINT ck_failure_events_matched_by CHECK ((matched_by = ANY (ARRAY['code'::text, 'fingerprint'::text, 'new'::text])));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_failure_events_outcome') THEN
    ALTER TABLE radar.failure_events ADD CONSTRAINT ck_failure_events_outcome CHECK ((outcome = ANY (ARRAY['fixed'::text, 'not_fixed'::text, 'unknown'::text])));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_failure_patterns_cause_length') THEN
    ALTER TABLE radar.failure_patterns ADD CONSTRAINT ck_failure_patterns_cause_length CHECK ((char_length(cause) <= 200));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_failure_patterns_status') THEN
    ALTER TABLE radar.failure_patterns ADD CONSTRAINT ck_failure_patterns_status CHECK ((status = ANY (ARRAY['proposed'::text, 'active'::text, 'retired'::text])));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_message_feedback_rating') THEN
    ALTER TABLE radar.message_feedback ADD CONSTRAINT ck_message_feedback_rating CHECK ((rating = ANY (ARRAY['up'::text, 'down'::text])));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_project_memory_kind') THEN
    ALTER TABLE radar.project_memory ADD CONSTRAINT ck_project_memory_kind CHECK ((kind = ANY (ARRAY['rule'::text, 'environment'::text, 'schedule'::text, 'dependency'::text, 'contact'::text, 'verify_after'::text, 'quirk'::text])));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_project_memory_origin') THEN
    ALTER TABLE radar.project_memory ADD CONSTRAINT ck_project_memory_origin CHECK ((origin = ANY (ARRAY['human'::text, 'incident'::text, 'sop'::text])));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_project_memory_status') THEN
    ALTER TABLE radar.project_memory ADD CONSTRAINT ck_project_memory_status CHECK ((status = ANY (ARRAY['proposed'::text, 'active'::text, 'retired'::text])));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_project_memory_text_length') THEN
    ALTER TABLE radar.project_memory ADD CONSTRAINT ck_project_memory_text_length CHECK (((char_length(text) >= 1) AND (char_length(text) <= 300)));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_sop_documents_status') THEN
    ALTER TABLE radar.sop_documents ADD CONSTRAINT ck_sop_documents_status CHECK ((status = ANY (ARRAY['active'::text, 'replaced'::text])));
  END IF;
END $$;

-- At most one active SOP per project.
CREATE UNIQUE INDEX IF NOT EXISTS uq_sop_documents_one_active
  ON radar.sop_documents (project) WHERE status = 'active';

-- Foreign keys to WatchTower's users (cross-schema, so Prisma can't declare them).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'audit_log_user_id_fkey') THEN
    ALTER TABLE radar.audit_log ADD CONSTRAINT audit_log_user_id_fkey FOREIGN KEY (user_id)
      REFERENCES public."User"(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_analytics_user_id_fkey') THEN
    ALTER TABLE radar.chat_analytics ADD CONSTRAINT chat_analytics_user_id_fkey FOREIGN KEY (user_id)
      REFERENCES public."User"(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_threads_claimed_by_user_id_fkey') THEN
    ALTER TABLE radar.chat_threads ADD CONSTRAINT chat_threads_claimed_by_user_id_fkey FOREIGN KEY (claimed_by_user_id)
      REFERENCES public."User"(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'failure_patterns_approved_by_fkey') THEN
    ALTER TABLE radar.failure_patterns ADD CONSTRAINT failure_patterns_approved_by_fkey FOREIGN KEY (approved_by)
      REFERENCES public."User"(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'message_feedback_user_id_fkey') THEN
    ALTER TABLE radar.message_feedback ADD CONSTRAINT message_feedback_user_id_fkey FOREIGN KEY (user_id)
      REFERENCES public."User"(id) ON UPDATE CASCADE ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'project_memory_approved_by_fkey') THEN
    ALTER TABLE radar.project_memory ADD CONSTRAINT project_memory_approved_by_fkey FOREIGN KEY (approved_by)
      REFERENCES public."User"(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'project_memory_created_by_fkey') THEN
    ALTER TABLE radar.project_memory ADD CONSTRAINT project_memory_created_by_fkey FOREIGN KEY (created_by)
      REFERENCES public."User"(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sop_documents_uploaded_by_fkey') THEN
    ALTER TABLE radar.sop_documents ADD CONSTRAINT sop_documents_uploaded_by_fkey FOREIGN KEY (uploaded_by)
      REFERENCES public."User"(id) ON UPDATE CASCADE ON DELETE SET NULL;
  END IF;
END $$;

-- Tool permissions. A tool with no row here is invisible to the agent; requires_consent
-- makes it pause for a human's approval (every tool that changes anything).
INSERT INTO radar.rbac_permissions (platform, tool_name, allowed, requires_consent) VALUES
  ('adf', 'cancel_pipeline_run', true, true),
  ('adf', 'cancel_trigger_run', true, true),
  ('adf', 'create_data_flow', true, true),
  ('adf', 'create_dataset', true, true),
  ('adf', 'create_global_parameter', true, true),
  ('adf', 'create_linked_service', true, true),
  ('adf', 'create_pipeline', true, true),
  ('adf', 'create_trigger', true, true),
  ('adf', 'get_activity_run_error', true, false),
  ('adf', 'get_activity_run_history', true, false),
  ('adf', 'get_activity_run_io', true, false),
  ('adf', 'get_data_flow_definition', true, false),
  ('adf', 'get_data_flow_definition_raw', true, false),
  ('adf', 'get_dataset_definition', true, false),
  ('adf', 'get_dataset_definition_raw', true, false),
  ('adf', 'get_global_parameter_definition_raw', true, false),
  ('adf', 'get_integration_runtime_status', true, false),
  ('adf', 'get_linked_service', true, false),
  ('adf', 'get_linked_service_definition_raw', true, false),
  ('adf', 'get_pipeline_definition', true, false),
  ('adf', 'get_pipeline_definition_raw', true, false),
  ('adf', 'get_pipeline_run_history', true, false),
  ('adf', 'get_pipeline_run_status', true, false),
  ('adf', 'get_trigger', true, false),
  ('adf', 'get_trigger_run_history', true, false),
  ('adf', 'list_activity_runs', true, false),
  ('adf', 'list_data_flows', true, false),
  ('adf', 'list_datasets', true, false),
  ('adf', 'list_global_parameters', true, false),
  ('adf', 'list_linked_services', true, false),
  ('adf', 'list_pipeline_runs', true, false),
  ('adf', 'list_pipelines', true, false),
  ('adf', 'list_triggers', true, false),
  ('adf', 'rerun_pipeline', true, true),
  ('adf', 'rerun_trigger_run', true, true),
  ('adf', 'start_integration_runtime', true, true),
  ('adf', 'start_trigger', true, true),
  ('adf', 'stop_trigger', true, true),
  ('adf', 'update_data_flow_definition', true, true),
  ('adf', 'update_dataset_definition', true, true),
  ('adf', 'update_global_parameter_definition', true, true),
  ('adf', 'update_linked_service_definition', true, true),
  ('adf', 'update_pipeline_definition', true, true),
  ('adf', 'update_trigger_definition', true, true),
  ('radar', 'propose_failure_pattern', true, true),
  ('radar', 'propose_memory', true, true)
ON CONFLICT (platform, tool_name) DO NOTHING;
