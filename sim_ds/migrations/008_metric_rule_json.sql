-- 008: metric definitions can carry the scenario-style rule JSON directly.
BEGIN;
ALTER TABLE metric_def
  ADD COLUMN IF NOT EXISTS trigger_functions JSONB NOT NULL DEFAULT '[]';
ALTER TABLE metric_def
  ADD COLUMN IF NOT EXISTS functions JSONB NOT NULL DEFAULT '[]';
COMMIT;
