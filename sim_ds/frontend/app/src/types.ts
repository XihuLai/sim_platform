export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface Scenario {
  id: string;
  name: string;
  description?: string | null;
  version: number;
  status: string;
  source_type: string;
  duration_ms?: number | null;
  tags: string[];
  owner?: string | null;
  project?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface UserAccount {
  id: string;
  username: string;
  display_name: string;
  role: "super_admin" | "admin" | "user";
  status: "active" | "disabled";
  project: string;
  max_priority: number;
  max_running_cases?: number | null;
  max_cpu?: number | null;
  max_mem_gb?: number | null;
  max_gpu?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TagOption {
  id: number;
  name: string;
  category?: string | null;
  usage: number;
}

export interface ScenarioMetric {
  id: string;
  name: string;
  desc?: string;
  business_type?: string;
  run_mode?: "async" | "sync";
  level?: string;
  is_global?: boolean;
  trigger_functions?: MetricRuleFunction[];
  trigger_ops?: Array<"AND" | "OR">;
  functions?: MetricRuleFunction[];
  ops?: Array<"AND" | "OR">;
  ret?: "pass" | "fail";
  action?: string;
}

export interface ScenarioSource {
  type: string;
  log_id: string;
  log_uri: string;
  log_checksum: string;
  format: string;
}

export interface ScenarioDetail extends Scenario {
  scenario_id?: string;
  source: ScenarioSource;
  time_window: { start_ts: number; end_ts: number; trigger_ts: number };
  metrics: ScenarioMetric[];
  extra: Record<string, unknown>;
  file_checksum: string;
  publish_state: string;
}

export interface MetricInstance {
  metric_def_id: string;
  metric_def_ver: number;
  alias?: string | null;
  config: Record<string, unknown>;
  enabled: boolean;
}

export interface SetSummary {
  id: string;
  name: string;
  description?: string | null;
  current_version: number;
  frozen: boolean;
  visibility: "private" | "public";
  owner?: string | null;
  project?: string | null;
  member_count: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SetMember {
  scenario_id: string;
  scenario_version: number;
  sort_order: number;
  scenario_name?: string | null;
  scenario_status?: string | null;
}

export interface Task {
  task_id: string;
  name: string;
  project: string;
  owner?: string | null;
  set_id: string;
  set_name?: string | null;
  set_version: number;
  priority: number;
  status: string;
  total_cases: number;
  counts: Record<string, number>;
  progress: number;
  pass_count: number;
  fail_count: number;
  metrics: string[];
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  runtime: RuntimeConfig;
}

export interface CaseRun {
  case_run_id: string;
  task_id: string;
  scenario_id: string;
  scenario_version: number;
  status: string;
  attempt: number;
  worker_id?: string | null;
  exit_code?: number | null;
  output_uri?: string | null;
  reason?: string | null;
  metrics: Record<string, { value: unknown; pass?: boolean | null }>;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface RuntimeConfig {
  binary_id: string;
  args: string[];
  env: Record<string, string>;
  resource: { cpu: number; mem_gb: number; gpu: number };
  timeout_sec: number;
  retry: { max: number; on: string[] };
}

export interface TaskSummary {
  task: Task;
  text: string;
  pass_rate: number;
  metrics: Array<{ metric_key: string; cnt: number; pass_cnt: number; p95_value?: number | null }>;
  charts: {
    status: Array<{ key: string; value: number }>;
    metrics: Array<{ key: string; cnt: number; pass_cnt: number; p95?: number | null }>;
  };
  failures: Array<Partial<CaseRun> & { id: string }>;
}

export interface MetricRuleFunction {
  name?: string;
  function_field_name?: string;
  template_id: string;
  env: Record<string, unknown>;
}

export interface MetricDef {
  id: string;
  version: number;
  type_id: string;
  name: string;
  level?: string | null;
  business_type?: string | null;
  run_mode?: "async" | "sync";
  is_global?: boolean;
  status: string;
  trigger_templates: Array<{ template_id: string; required?: boolean }>;
  trigger_functions?: MetricRuleFunction[];
  trigger_ops?: Array<"AND" | "OR">;
  function_templates: Array<{ template_id: string; required?: boolean }>;
  functions?: MetricRuleFunction[];
  ops?: Array<"AND" | "OR">;
  ret?: "pass" | "fail";
  action?: string;
  description?: string | null;
}

export interface MetricType {
  id: string;
  category_id: string;
  parent_id?: string | null;
  name: string;
  sort_order: number;
}

export interface MetricTemplate {
  id: string;
  name: string;
  kind: "trigger" | "function";
  env_schema: Record<string, unknown>;
  env_example: Record<string, unknown>;
  status: string;
}

export interface DataSource {
  source_id: string;
  kind: string;
  uri: string;
  format: string;
  project: string;
  duration_ms: number;
  channels: ChannelIndex[];
  status: "pending" | "indexing" | "ready" | "failed";
  progress: number;
  error?: string | null;
  created_at?: string | null;
}

export interface ChannelIndex {
  name: string;
  type: "video" | "pointcloud" | "timeseries" | "pose";
  fps: number;
  chunks?: Array<{ start_ms: number; end_ms: number; uri: string; index: number }>;
}

export interface ChunkPayload {
  source_id: string;
  channel: string;
  type: string;
  fps: number;
  start_ms: number;
  end_ms: number;
  samples?: Array<Record<string, number>>;
  frames?: Array<Record<string, unknown>>;
}

export interface QueueStats {
  by_status: Array<{ status: string; tasks: number; total_cases: number; waiting_cases: number; running_cases: number; oldest_created?: string | null }>;
  by_priority: Array<{ priority: number; tasks: number; waiting: number }>;
  generated_at: string;
}

export interface Overview {
  scenarios: number;
  sets: number;
  frozen_sets: number;
  sources: number;
  tasks: Array<{ status: string; tasks: number; cases: number; succeeded: number; passed: number }>;
  total_cases: number;
  succeeded_cases: number;
  passed_cases: number;
  pass_rate: number;
  queue_depth: number;
  running_cases: number;
}
