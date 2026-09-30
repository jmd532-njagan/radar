-- A project's ADF connection details now come only from WatchTower's own public."Credential"
-- (written by its Integrations tab), so RADAR's hand-seeded copy of the non-secret identifiers
-- is gone. failure_events.factory_name stays as a plain column recording which factory the
-- integration pointed at when the failure arrived.
ALTER TABLE "failure_events" DROP CONSTRAINT IF EXISTS "failure_events_project_factory_name_fkey";
DROP TABLE "credentials";
