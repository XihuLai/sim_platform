-- 001_init.sql：基础表（scenario/tag/set/task/case_run/worker/outbox）
BEGIN;

CREATE TABLE scenario (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  description     TEXT,
  current_version INT  NOT NULL DEFAULT 1,
  source_type     TEXT NOT NULL,
  log_id          TEXT,
  log_uri         TEXT,
  log_checksum    TEXT,
  file_uri        TEXT NOT NULL,
  file_checksum   TEXT NOT NULL,
  start_ts        BIGINT,
  end_ts          BIGINT,
  trigger_ts      BIGINT,
  duration_ms  BIGINT GENERATED ALWAYS AS (end_ts - start_ts) STORED,
  extra           JSONB NOT NULL DEFAULT '{}',
  owner           TEXT,
  project         TEXT,
  status          TEXT NOT NULL DEFAULT 'active',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_scn_project ON scenario(project) WHERE status='active';
CREATE INDEX idx_scn_time    ON scenario(start_ts, end_ts);
CREATE INDEX idx_scn_extra   ON scenario USING GIN (extra jsonb_path_ops);
CREATE INDEX idx_scn_duration ON scenario(duration_ms) WHERE status='active';


CREATE TABLE scenario_version (
  scenario_id   TEXT NOT NULL REFERENCES scenario(id),
  version       INT  NOT NULL,
  file_uri      TEXT NOT NULL,
  file_checksum TEXT NOT NULL,
  change_note   TEXT,
  created_by    TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (scenario_id, version)
);

CREATE TABLE tag (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  category   TEXT,
  parent_id  BIGINT REFERENCES tag(id),
  color      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (name, category)
);
CREATE TABLE scenario_tag (
  scenario_id TEXT NOT NULL REFERENCES scenario(id),
  tag_id      BIGINT NOT NULL REFERENCES tag(id),
  PRIMARY KEY (scenario_id, tag_id)
);
CREATE INDEX idx_scn_tag ON scenario_tag(tag_id);

CREATE TABLE scenario_set (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  description     TEXT,
  current_version INT  NOT NULL DEFAULT 1,
  frozen          BOOLEAN NOT NULL DEFAULT false,
  owner           TEXT,
  project         TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE scenario_set_version (
  set_id       TEXT NOT NULL REFERENCES scenario_set(id),
  version      INT  NOT NULL,
  snapshot_uri TEXT NOT NULL,
  snapshot_sha TEXT NOT NULL,
  member_count INT  NOT NULL,
  frozen_at    TIMESTAMPTZ,
  created_by   TEXT,
  PRIMARY KEY (set_id, version)
);
CREATE TABLE scenario_set_member (
  set_id           TEXT NOT NULL,
  set_version      INT  NOT NULL,
  scenario_id      TEXT NOT NULL REFERENCES scenario(id),
  scenario_version INT  NOT NULL,
  sort_order       INT  NOT NULL DEFAULT 0,
  PRIMARY KEY (set_id, set_version, scenario_id)
);
CREATE INDEX idx_set_member_scn ON scenario_set_member(scenario_id);
CREATE INDEX idx_set_member_ver ON scenario_set_member(set_id, set_version, sort_order);

CREATE TABLE sim_task (
  id             TEXT PRIMARY KEY,
  name           TEXT,
  set_id         TEXT NOT NULL,
  set_version    INT  NOT NULL,
  priority       SMALLINT NOT NULL DEFAULT 5,
  runtime_config JSONB NOT NULL,
  metrics        TEXT[] NOT NULL,
  project        TEXT,
  owner          TEXT,
  total_cases    INT  NOT NULL DEFAULT 0,
  status         TEXT NOT NULL DEFAULT 'queued',
  runtime_hash   TEXT NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at     TIMESTAMPTZ,
  finished_at    TIMESTAMPTZ,
  UNIQUE (set_id, set_version, runtime_hash, metrics)
);
CREATE INDEX idx_task_status ON sim_task(status, created_at);

-- case_run 主表（001 先建普通表；003 转分区）
CREATE TABLE case_run (
  id                 TEXT NOT NULL,
  task_id            TEXT NOT NULL REFERENCES sim_task(id),
  scenario_id        TEXT NOT NULL,
  scenario_version   INT  NOT NULL,
  priority           SMALLINT NOT NULL,
  effective_priority SMALLINT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'queued',
  attempt            SMALLINT NOT NULL DEFAULT 0,
  worker_id          TEXT,
  resource_req       JSONB NOT NULL,
  output_uri         TEXT,
  exit_code          INT,
  reason             TEXT,
  waiting_since      TIMESTAMPTZ NOT NULL DEFAULT now(),
  heartbeat_at       TIMESTAMPTZ,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at         TIMESTAMPTZ,
  finished_at        TIMESTAMPTZ,
  PRIMARY KEY (id, created_at)
);
CREATE INDEX idx_case_sched ON case_run(status, effective_priority, waiting_since)
  WHERE status IN ('queued','scheduled');
CREATE INDEX idx_case_task ON case_run(task_id, status, created_at);
CREATE INDEX idx_case_scn  ON case_run(scenario_id, created_at);

CREATE TABLE project_quota (
  project                TEXT PRIMARY KEY,
  max_running_cases      INT,
  reserved_high_priority INT,
  max_cpu                INT,
  max_mem_gb             INT
);

CREATE TABLE worker (
  id            TEXT PRIMARY KEY,
  executor_type TEXT NOT NULL,
  status        TEXT NOT NULL,
  capacity      JSONB NOT NULL,
  used          JSONB NOT NULL DEFAULT '{}',
  labels        JSONB NOT NULL DEFAULT '{}',
  heartbeat_at  TIMESTAMPTZ,
  started_at    TIMESTAMPTZ
);

CREATE TABLE outbox (
  id          BIGSERIAL PRIMARY KEY,
  case_run_id TEXT NOT NULL,
  payload     JSONB NOT NULL,
  published   BOOLEAN NOT NULL DEFAULT false,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_outbox_unpub ON outbox(id) WHERE published=false;

COMMIT;