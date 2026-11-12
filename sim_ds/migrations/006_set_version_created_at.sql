-- 006: scenario_set_version needs a stable ordering key for crash recovery.
BEGIN;
ALTER TABLE scenario_set_version
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_set_version_pending
  ON scenario_set_version(publish_state, created_at);
COMMIT;
