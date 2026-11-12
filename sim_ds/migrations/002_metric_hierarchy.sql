-- 002_metric_hierarchy.sql：Metric 五层模型（v1.2 重写）
-- 注意：若已有 v1.1 的旧表，请先备份并按 DROP/重建流程执行。
BEGIN;

-- ── 1) 分类（固定 5 类）──────────────────────
CREATE TABLE metric_category (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  sort_order  INT  NOT NULL DEFAULT 0,
  description TEXT
);
INSERT INTO metric_category(id,name,sort_order) VALUES
  ('comfort','舒适类',1),
  ('compliance','合规类',2),
  ('safety','安全类',3),
  ('efficiency','效率类',4),
  ('navigation','导航类',5);

-- ── 2) 细分类型（树形）──────────────────────
CREATE TABLE metric_type (
  id          TEXT PRIMARY KEY,
  category_id TEXT NOT NULL REFERENCES metric_category(id),
  parent_id   TEXT REFERENCES metric_type(id),
  name        TEXT NOT NULL,
  sort_order  INT  NOT NULL DEFAULT 0,
  description TEXT,
  status      TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX idx_mtype_cat    ON metric_type(category_id);
CREATE INDEX idx_mtype_parent ON metric_type(parent_id);

-- ── 3) 函数/触发模板（新增层）────────────────
CREATE TABLE metric_template (
  id          TEXT PRIMARY KEY,              -- "9" / "30" / "27" ...
  name        TEXT NOT NULL,                 -- "时间区间" / "急刹" ...
  kind        TEXT NOT NULL,                 -- trigger | function
  env_schema  JSONB NOT NULL,                -- env 字段 JSON Schema
  env_example JSONB NOT NULL DEFAULT '{}',
  status      TEXT NOT NULL DEFAULT 'active',
  description TEXT
);
CREATE INDEX idx_mtpl_kind ON metric_template(kind, status);

-- ── 4) Metric 定义（规则组合 + 元信息）────────
CREATE TABLE metric_def (
  id                  TEXT NOT NULL,
  version             INT  NOT NULL DEFAULT 1,
  type_id             TEXT NOT NULL REFERENCES metric_type(id),
  name                TEXT NOT NULL,
  level               TEXT,                  -- S0 | S1 | S2 ...
  business_type       TEXT,                  -- dpc | ...
  run_mode            TEXT NOT NULL DEFAULT 'async',  -- async | sync
  is_global           BOOLEAN NOT NULL DEFAULT false,
  trigger_templates   JSONB NOT NULL DEFAULT '[]',    -- [{"template_id":"9","slot":0,"required":true}]
  trigger_ops         JSONB NOT NULL DEFAULT '[]',    -- ["AND"] / ["OR"]
  function_templates  JSONB NOT NULL DEFAULT '[]',
  ops                 JSONB NOT NULL DEFAULT '[]',
  ret                 TEXT NOT NULL DEFAULT 'pass',   -- pass | fail
  action              TEXT NOT NULL DEFAULT 'not_stop_sim',
  status              TEXT NOT NULL DEFAULT 'active',
  description         TEXT,
  PRIMARY KEY (id, version)
);
CREATE INDEX idx_mdef_type  ON metric_def(type_id, status);
CREATE INDEX idx_mdef_level ON metric_def(level) WHERE status='active';

-- ── 5) 场景实例（config 规则实例）────────────
CREATE TABLE scenario_metric (
  id              BIGSERIAL PRIMARY KEY,
  scenario_id     TEXT NOT NULL REFERENCES scenario(id),
  metric_def_id   TEXT NOT NULL,
  metric_def_ver  INT  NOT NULL,
  alias           TEXT,
  config          JSONB NOT NULL,            -- 完整规则实例
  enabled         BOOLEAN NOT NULL DEFAULT true,
  extra           JSONB NOT NULL DEFAULT '{}',
  UNIQUE (scenario_id, metric_def_id, alias),
  FOREIGN KEY (metric_def_id, metric_def_ver)
    REFERENCES metric_def(id, version)
);
CREATE INDEX idx_scn_metric_scn ON scenario_metric(scenario_id);
CREATE INDEX idx_scn_metric_def ON scenario_metric(metric_def_id);
CREATE INDEX idx_scn_metric_cfg ON scenario_metric USING GIN (config jsonb_path_ops);

-- ── 6) 内置模板示例（trigger 9 时间区间；function 30 急刹）──
INSERT INTO metric_template(id,name,kind,env_schema,env_example) VALUES
('9','时间区间','trigger',
 '{"type":"object","required":["开始时间","结束时间"],"properties":{
   "开始时间":{"type":"object","required":["field_name","value","is_number","unit"],
     "properties":{"field_name":{"const":"start_time"},"value":{"type":"string"},
     "is_number":{"type":"boolean"},"unit":{"type":"string"}}},
   "结束时间":{"type":"object","required":["field_name","value","is_number","unit"],
     "properties":{"field_name":{"const":"end_time"},"value":{"type":"string"},
     "is_number":{"type":"boolean"},"unit":{"type":"string"}}}}}',
 '{"开始时间":{"field_name":"start_time","value":"","is_number":false,"unit":""},
   "结束时间":{"field_name":"end_time","value":"","is_number":false,"unit":""}}'),
('30','急刹','function',
 '{"type":"object","required":["jerk一级阈值","jerk二级阈值","加速度阈值"],
   "properties":{
   "jerk一级阈值":{"type":"object","required":["field_name","value","is_number","unit"],
     "properties":{"field_name":{"const":"jerk1_threshold"},"value":{"type":"string"},
     "is_number":{"type":"boolean"},"unit":{"type":"string"}}},
   "jerk二级阈值":{"type":"object","required":["field_name","value","is_number","unit"],
     "properties":{"field_name":{"const":"jerk2_threshold"},"value":{"type":"string"},
     "is_number":{"type":"boolean"},"unit":{"type":"string"}}},
   "加速度阈值":{"type":"object","required":["field_name","value","is_number","unit"],
     "properties":{"field_name":{"const":"acc_threshold"},"value":{"type":"string"},
     "is_number":{"type":"boolean"},"unit":{"type":"string"}}}}}',
 '{"jerk一级阈值":{"field_name":"jerk1_threshold","value":"-3","is_number":true,"unit":""},
   "jerk二级阈值":{"field_name":"jerk2_threshold","value":"-4","is_number":true,"unit":""},
   "加速度阈值":{"field_name":"acc_threshold","value":"-3","is_number":true,"unit":""}}');

COMMIT;