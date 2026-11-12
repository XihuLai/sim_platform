-- 004_scheduler_integrity.sql
-- v2 contract migration. Do not edit migrations/001~003.
-- Apply with v1 writers stopped after file-checksum and duplicate-run preflight;
-- drain or explicitly terminate all v1 expanding tasks before applying.
-- resume writes only after the v2 application is deployed.
-- Rollback: drop the new indexes/table/columns and restore the legacy task
-- uniqueness constraint only after resolving duplicate legacy
-- (set_id, set_version, runtime_hash, metrics) keys.
BEGIN;

ALTER TABLE scenario_version
  ADD COLUMN publish_state TEXT NOT NULL DEFAULT 'published'
  CHECK (publish_state IN ('pending', 'published', 'failed', 'unavailable'));
ALTER TABLE scenario_set_version
  ADD COLUMN publish_state TEXT NOT NULL DEFAULT 'published'
  CHECK (publish_state IN ('pending', 'published', 'failed', 'unavailable'));
ALTER TABLE scenario_version
  ALTER COLUMN publish_state DROP DEFAULT;
ALTER TABLE scenario_set_version
  ALTER COLUMN publish_state DROP DEFAULT;
ALTER TABLE scenario_version
  ADD COLUMN expected_version INT NOT NULL DEFAULT 0 CHECK (expected_version >= 0);
ALTER TABLE scenario_set_version
  ADD COLUMN expected_version INT NOT NULL DEFAULT 0 CHECK (expected_version >= 0);
UPDATE scenario_version SET expected_version = version - 1;
UPDATE scenario_set_version SET expected_version = version - 1;
ALTER TABLE scenario_version
  ALTER COLUMN expected_version DROP DEFAULT;
ALTER TABLE scenario_set_version
  ALTER COLUMN expected_version DROP DEFAULT;

ALTER TABLE sim_task
  ADD COLUMN request_fingerprint TEXT,
  ADD COLUMN dedup_enabled BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN snapshot_sha TEXT,
  ADD COLUMN engine_digest TEXT;
UPDATE sim_task
SET dedup_enabled = false
WHERE request_fingerprint IS NULL;
ALTER TABLE sim_task
  ADD CONSTRAINT ck_sim_task_dedup_fingerprint
  CHECK (NOT dedup_enabled OR request_fingerprint IS NOT NULL);
ALTER TABLE case_run
  ADD COLUMN last_result_report_id TEXT;
ALTER TABLE case_result
  ADD COLUMN attempt SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE case_result
  ALTER COLUMN attempt DROP DEFAULT;
ALTER TABLE task_expand_cursor
  ADD COLUMN case_run_created_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE sim_task
  DROP CONSTRAINT IF EXISTS sim_task_set_id_set_version_runtime_hash_metrics_key;

CREATE UNIQUE INDEX uq_sim_task_request_fingerprint
  ON sim_task(request_fingerprint)
  WHERE dedup_enabled AND request_fingerprint IS NOT NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM case_run
    GROUP BY task_id, scenario_id, created_at
    HAVING COUNT(*) > 1
  ) THEN
    RAISE EXCEPTION
      'case_run has duplicate (task_id, scenario_id, created_at); reconcile before migration 004';
  END IF;
END;
$$;

CREATE UNIQUE INDEX uq_case_run_task_scenario_created
  ON case_run(task_id, scenario_id, created_at);

CREATE TABLE resource_reservation (
  case_run_id TEXT NOT NULL,
  attempt     SMALLINT NOT NULL,
  project     TEXT NOT NULL REFERENCES project_quota(project) ON DELETE RESTRICT,
  worker_id   TEXT NOT NULL REFERENCES worker(id) ON DELETE RESTRICT,
  cpu         INT NOT NULL DEFAULT 0 CHECK (cpu >= 0),
  mem_gb      INT NOT NULL DEFAULT 0 CHECK (mem_gb >= 0),
  gpu         INT NOT NULL DEFAULT 0 CHECK (gpu >= 0),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  released_at TIMESTAMPTZ,
  PRIMARY KEY (case_run_id, attempt)
);

CREATE INDEX idx_resource_reservation_worker_active
  ON resource_reservation(worker_id)
  WHERE released_at IS NULL;
CREATE INDEX idx_resource_reservation_project_active
  ON resource_reservation(project)
  WHERE released_at IS NULL;

CREATE TABLE task_control_request (
  request_id   TEXT PRIMARY KEY,
  task_id      TEXT NOT NULL REFERENCES sim_task(id) ON DELETE RESTRICT,
  command      TEXT NOT NULL CHECK (command IN ('pause', 'resume', 'cancel')),
  requested_by TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'processing', 'completed', 'rejected')),
  result_code  TEXT,
  result_detail JSONB NOT NULL DEFAULT '{}',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX idx_task_control_pending
  ON task_control_request(created_at)
  WHERE status IN ('pending', 'processing');
CREATE UNIQUE INDEX uq_task_control_one_inflight
  ON task_control_request(task_id)
  WHERE status IN ('pending', 'processing');

DO $$
DECLARE
  month_offset INT;
  range_start DATE;
  range_end DATE;
  partition_suffix TEXT;
BEGIN
  FOR month_offset IN 0..3 LOOP
    range_start := (
      date_trunc('month', CURRENT_DATE) + make_interval(months => month_offset)
    )::DATE;
    range_end := (range_start + INTERVAL '1 month')::DATE;
    partition_suffix := to_char(range_start, 'YYYY_MM');

    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS %I PARTITION OF case_run FOR VALUES FROM (%L) TO (%L)',
      'case_run_' || partition_suffix, range_start, range_end
    );
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS %I PARTITION OF case_result FOR VALUES FROM (%L) TO (%L)',
      'case_result_' || partition_suffix, range_start, range_end
    );
  END LOOP;
END;
$$;

COMMIT;
