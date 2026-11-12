-- 005_platform_support.sql
-- Additive v2.0 support: task batch/seed persistence, audit log, playback index,
-- GPU quota and archive manifests. Does not modify migrations 001-004.
BEGIN;

ALTER TABLE sim_task ADD COLUMN IF NOT EXISTS batch JSONB NOT NULL DEFAULT '{}';
ALTER TABLE sim_task ADD COLUMN IF NOT EXISTS seed BIGINT;
ALTER TABLE project_quota ADD COLUMN IF NOT EXISTS max_gpu INT;

CREATE TABLE IF NOT EXISTS audit_log (
  id          BIGSERIAL PRIMARY KEY,
  actor       TEXT NOT NULL,
  project     TEXT NOT NULL,
  action      TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  detail      JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_project_time ON audit_log(project, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_log(resource_type, resource_id, created_at DESC);

CREATE TABLE IF NOT EXISTS data_source (
  id          TEXT PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('record','sim_output')),
  uri         TEXT NOT NULL,
  format      TEXT NOT NULL,
  project     TEXT NOT NULL,
  owner       TEXT NOT NULL,
  index_uri   TEXT,
  duration_ms BIGINT NOT NULL DEFAULT 0,
  channels    JSONB NOT NULL DEFAULT '[]',
  status      TEXT NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','indexing','ready','failed')),
  progress    INT NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_source_project ON data_source(project, created_at DESC);

CREATE TABLE IF NOT EXISTS archive_export (
  export_id    TEXT PRIMARY KEY,
  task_id      TEXT NOT NULL,
  partition_name TEXT NOT NULL,
  month        TEXT NOT NULL,
  parquet_uri  TEXT NOT NULL,
  row_count    BIGINT NOT NULL DEFAULT 0,
  checksum     TEXT,
  status       TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending','exported','completed','failed')),
  attempts     INT NOT NULL DEFAULT 0,
  error        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  UNIQUE (partition_name, task_id)
);

CREATE INDEX IF NOT EXISTS idx_case_run_task_cursor ON case_run(task_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_case_run_task_status ON case_run(task_id, status, created_at);

COMMIT;
