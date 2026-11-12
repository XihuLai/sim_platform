-- 003_partition_and_preagg.sql：分区 + 预聚合 + 展开游标 + 结果表
-- 注意：分区改造需在低峰期执行；此处给出父表重建方案。
BEGIN;

-- 1) case_run 转分区（重命名旧表 → 建分区父表 → 迁移 → 删旧）
ALTER TABLE case_run RENAME TO case_run_old;

CREATE TABLE case_run (
  id                 TEXT NOT NULL,
  task_id            TEXT NOT NULL,
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
) PARTITION BY RANGE (created_at);

-- 示例分区（生产由定时任务维护）
CREATE TABLE case_run_2026_05 PARTITION OF case_run
  FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE case_run_2026_06 PARTITION OF case_run
  FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE case_run_2026_07 PARTITION OF case_run
  FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');

INSERT INTO case_run SELECT * FROM case_run_old;
DROP TABLE case_run_old;

CREATE INDEX idx_case_sched ON case_run(status, effective_priority, waiting_since)
  WHERE status IN ('queued','scheduled');
CREATE INDEX idx_case_task ON case_run(task_id, status, created_at);
CREATE INDEX idx_case_scn  ON case_run(scenario_id, created_at);

-- 2) case_result 分区表
CREATE TABLE case_result (
  case_run_id  TEXT NOT NULL,
  task_id      TEXT NOT NULL,
  scenario_id  TEXT NOT NULL,
  metric_key   TEXT NOT NULL,
  value        DOUBLE PRECISION,
  pass         BOOLEAN,
  extra        JSONB NOT NULL DEFAULT '{}',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (case_run_id, metric_key, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE case_result_2026_05 PARTITION OF case_result
  FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE case_result_2026_06 PARTITION OF case_result
  FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE case_result_2026_07 PARTITION OF case_result
  FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE INDEX idx_result_task ON case_result(task_id, pass, created_at);

-- 3) 预聚合
CREATE TABLE task_summary (
  task_id     TEXT PRIMARY KEY REFERENCES sim_task(id),
  total       INT  NOT NULL DEFAULT 0,
  queued      INT  NOT NULL DEFAULT 0,
  scheduled   INT  NOT NULL DEFAULT 0,
  running     INT  NOT NULL DEFAULT 0,
  paused      INT  NOT NULL DEFAULT 0,
  succeeded   INT  NOT NULL DEFAULT 0,
  failed      INT  NOT NULL DEFAULT 0,
  canceled    INT  NOT NULL DEFAULT 0,
  timeout     INT  NOT NULL DEFAULT 0,
  worker_lost INT  NOT NULL DEFAULT 0,
  pass_count  INT  NOT NULL DEFAULT 0,
  fail_count  INT  NOT NULL DEFAULT 0,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE task_metric_agg (
  task_id    TEXT NOT NULL,
  metric_key TEXT NOT NULL,
  cnt        INT  NOT NULL DEFAULT 0,
  pass_cnt   INT  NOT NULL DEFAULT 0,
  sum_value  DOUBLE PRECISION NOT NULL DEFAULT 0,
  p95_value  DOUBLE PRECISION,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (task_id, metric_key)
);

-- 4) 展开游标
CREATE TABLE task_expand_cursor (
  task_id     TEXT PRIMARY KEY REFERENCES sim_task(id),
  set_id      TEXT NOT NULL,
  set_version INT  NOT NULL,
  shard_index INT  NOT NULL DEFAULT 0,
  last_offset INT  NOT NULL DEFAULT 0,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;