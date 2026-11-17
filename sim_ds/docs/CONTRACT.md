# 平台总契约 v2.0
> Architect 维护，所有 Agent 只读。冲突裁决顺序：
> 业务语义 → CONTRACT.md；技术选型 → CONTRACT-tech-stack.md；
> 存储/DDL → CONTRACT-storage.md；调度/执行 → CONTRACT-scheduler.md。
> 契约变更只允许向后兼容新增；破坏性变更须开新主版本并在 CHANGELOG 高亮。

## 0. 版本变更
- v2.3 : Metric ID 改为分类数字段（舒适 1001+/合规 2001+/安全 3001+/效率 4001+/导航 5001+），新增自动递增；Scenario.metrics 改为 metric.json 完整对象（id/name/desc + 规则），移除 enabled/metric_def_id/metric_def_ver/config 包装层。
- v2.2 : metric_def 支持直接保存 `trigger_functions` / `trigger_ops` / `functions` 规则 JSON（含 env），并按其中 template_id 自动派生模板引用；Metric 管理页展示定义 JSON。
- v2.1 : 统一 scenario_metric.config 不含 level/is_global（从 metric_def 查）；红线分阻塞级/建议级。
- v2.0（BREAKING）：统一异步展开门槛和状态迁移权责；定义快照发布与恢复、生产项目隔离、暂停/故障语义、复现输入及分区归档查询边界。
- v1.2：Metric 由四层改为**五层模型**（新增 metric_template）；
  scenario_metric 的 params 改为 config（规则表达式）；新增 level/
  business_type/run_mode/is_global/ret/action；校验改两级。
- v1.1：单任务 cases 修正为"几个 ~ 万级"；全局 case_run 10万~30万；
  Task 状态机新增 expanding；case 级接口改游标分页；新增预聚合与分区约定。
- v1.0：首版冻结。

## 1. 平台三域

┌─────────────── Scenario 域 ───────────────┐
│ 录包元数据 → Case 创建/编辑 → Metric 配置    │
│ → 标签 → ScenarioSet（版本化/冻结）          │
└──────────────────┬────────────────────────┘
                   │ set_id + version
┌──────────────────▼────────────────────────┐
│ Simulation 域                               │
│ SimTask(选集+RuntimeConfig+Priority)        │
│ → 展开(expanding) → Scheduler               │
│ (优先级/老化/抢占/暂停/取消/配额)            │
│ → Executor(Local | K8sPool | K8sJob)        │
│ → CaseRun × N（几个 ~ 万级并行）             │
│ → 结果聚合(预聚合) + 评测                    │
└──────────────────┬────────────────────────┘
                   │ output_uri
┌──────────────────▼────────────────────────┐
│ Playback 域                                 │
│ DataSource(raw|sim) → 索引 → 分片 → 播放器   │
│ 多通道同步 / seek / raw-vs-sim 对比          │
└─────────────────────────────────────────────┘

域间唯一耦合点：ScenarioSet、output_uri、DataSource 抽象。
跨域改动必须经 Architect。

## 2. 领域模型（JSON 事实源格式）

### 2.1 Scenario（文件：scenarios/{id}/v{n}.json）
```jsonc
{
  "scenario_id": "scn_20260512_a1b2",
  "name": "城市路口-行人横穿",
  "version": 1,
  "source": {
    "type": "record|synthetic",
    "log_id": "", "log_uri": "", "log_checksum": "sha256:...",
    "format": "rsclbag|mcap|bag|parquet",
  },
  "time_window": { "start_ts": 0, "end_ts": 0, "trigger_ts": 0 },
  "metrics": [
    {
      "metric_def_id": "safety.brake.hard",
      "metric_def_ver": 1,
      "alias": null,
      "config": {
        "trigger_functions": [
          { "name":"时间区间", "function_field_name":"时间区间",
            "template_id":"9",
            "env": {
              "开始时间": {"field_name":"start_time","value":"","is_number":false,"unit":""},
              "结束时间": {"field_name":"end_time","value":"","is_number":false,"unit":""}
            } },
          { "name":"时间区间", "function_field_name":"时间区间",
            "template_id":"9",
            "env": {
              "开始时间": {"field_name":"start_time","value":"2024-09-27-10-30-58","is_number":false,"unit":""},
              "结束时间": {"field_name":"end_time","value":"2024_09_27_10_31_45","is_number":false,"unit":""}
            } }
        ],
        "trigger_ops": ["AND"],
        "functions": [
          { "name":"急刹", "function_field_name":"急刹",
            "template_id":"30",
            "env": {
              "jerk一级阈值": {"field_name":"jerk1_threshold","value":"-3","is_number":true,"unit":""},
              "jerk二级阈值": {"field_name":"jerk2_threshold","value":"-4","is_number":true,"unit":""},
              "加速度阈值":   {"field_name":"acc_threshold","value":"-3","is_number":true,"unit":""}
            } }
        ],
        "ops": [],
        "ret": "pass",
        "action": "not_stop_sim",
        "level": "S0",
        "is_global": false
      },
      "enabled": true,
      "extra": {}
    }
  ],
  "tags": ["cut-in","rain","night"],
  "description": "",
  "extra": {},
  "created_by": "", "created_at": ""
}
```


### 2.2 ScenarioSet（文件：sets/{id}/v{n}.json；>2000 成员分片）
```jsonc
{ "set_id":"", "version":1, "name":"", "description":"",
  "frozen": true, "owner":"", "project":"",
  "members": [
    { "scenario_id":"", "scenario_version":1, "sort_order":0 }
  ],
  "checksum_self": "sha256:..." }
```

### 2.3 Metric 五层模型
```jsonc
// 1) metric_category（固定 5 类）
{ "id":"safety", "name":"安全类", "sort_order":1 }

// 2) metric_type（树形细分）
{ "id":"safety.brake", "category_id":"safety", "parent_id":null,
  "name":"制动类", "status":"active" }

// 3) metric_template（函数/触发模板，定义 env_schema）
//    kind=trigger：时间区间/事件等触发条件
//    kind=function：急刹/车道保持/画龙等检测函数
{ "id":"30", "name":"急刹", "kind":"function",
  "env_schema": {
    "type":"object",
    "required":["jerk1_threshold","jerk2_threshold","acc_threshold"],
    "properties":{
      "jerk一级阈值":{"type":"object","properties":{
        "field_name":{"const":"jerk1_threshold"},
        "value":{"type":"string"},"is_number":{"type":"boolean"},
        "unit":{"type":"string"}}},
      "jerk二级阈值":{"type":"object","properties":{
        "field_name":{"const":"jerk2_threshold"},...}},
      "加速度阈值":{"type":"object","properties":{
        "field_name":{"const":"acc_threshold"},...}}
    }
  },
  "env_example": {...} }

// 4) metric_def（规则组合 + 元信息；可选内嵌规则 JSON）
{ "id":"safety.brake.hard", "version":1, "type_id":"safety.brake",
  "name":"急刹", "level":"S0", "business_type":"dpc",
  "run_mode":"async", "is_global":false,
  "trigger_templates": [ {"template_id":"9","slot":0,"required":true} ],
  "trigger_functions": [ /* 同 scenario_metric.config.trigger_functions */ ],
  "trigger_ops": ["AND"],
  "function_templates": [ {"template_id":"30","slot":0,"required":true} ],
  "functions": [ /* 同 scenario_metric.config.functions */ ],
  "ops": [],
  "ret": "pass", "action": "not_stop_sim",
  "status":"active", "description":"" }

// 5) Scenario.metrics（场景文件内嵌完整 metric 对象，同 metric.json）
{ "id":"3001", "name":"急刹", "desc":"",
  "business_type":"dpc", "run_mode":"async", "level":"S0", "is_global":false,
  "trigger_functions":[], "trigger_ops":["AND"], "functions":[], "ops":[],
  "ret":"pass", "action":"not_stop_sim" }
// DB scenario_metric 仅为查询投影；文件中不再保存 metric_def_id/ver/config/enabled 包装层
```

### 2.4 RuntimeConfig / SimTask / CaseRun
```jsonc
// RuntimeConfig
{ "binary_id":"sim_engine@1.4.2",
  "args": ["--scenario","${SCENARIO_URI}","--out","${OUTPUT_DIR}"],
  "env":   { "SIM_SEED":"0", "LOG_LEVEL":"info" },
  "resource": { "cpu":2, "mem_gb":8, "gpu":0 },
  "timeout_sec": 600,
  "retry": { "max": 2, "on": ["timeout","worker_lost"] } }

// SimTask
{ "task_id":"", "name":"", "project":"", "owner":"",
  "set_id":"", "set_version":1,
  "runtime": RuntimeConfig,
  "priority": 0,                    // 0 最高 … 9 最低
  "batch": { "max_cases": 0, "shard_size": 1000 },
  "metrics": ["safe.collision.rate"],
  "status":"expanding|queued|scheduled|running|paused|succeeded|failed|canceled",
  "total_cases": 0,
  "snapshot_sha": "sha256:...",
  "request_fingerprint": "sha256:...",
  "created_at":"", "started_at":"", "finished_at":"" }

// CaseRun
{ "case_run_id":"", "task_id":"", "scenario_id":"", "scenario_version":1,
  "status":"queued|scheduled|running|paused|succeeded|failed|canceled|timeout|worker_lost",
  "attempt": 0, "worker_id":"", "exit_code": 0,
  "output_uri":"", "log_uri":"", "reason":"",
  "metrics": { "safe.collision.rate": { "value":0, "pass":true } },
  "started_at":"", "finished_at":"" }
```

### 2.5 DataSource / PlaybackSession
```jsonc
{ "source_id":"", "kind":"record|sim_output",
  "uri":"", "format":"mcap|bag|parquet|dir",
  "index_uri":"", "duration_ms":0,
  "channels":[ { "name":"camera_front","type":"video|pointcloud|timeseries|pose",
                 "fps":15, "range":[start_ts,end_ts] } ] }

{ "session_id":"", "source_ids":[], "mode":"single|compare",
  "sync_ts":0, "rate":1.0 }
```

### 3. API 最小集（前缀 /api）
场景：
POST/GET/PUT/DELETE /scenarios
GET /scenarios/{id}/versions
POST/GET/PUT/DELETE /sets
POST /sets/{id}:freeze （生成新的冻结版本并返回 version + snapshot_sha）
POST /sets/{id}:derive
POST /sets/{id}/versions
GET /sets/{id}/members?cursor&page_size （游标分页）
POST/GET/PUT/DELETE /metrics/categories
POST/GET/PUT/DELETE /metrics/types
POST/GET/PUT/DELETE /metrics/templates （新增：模板管理）
POST/GET/PUT/DELETE /metrics/defs
POST /sources:extract

仿真：
POST /tasks （body: SimTask；>500 异步展开）
GET /tasks?cursor&page_size&status&priority&project
GET /tasks/{id}
POST /tasks/{id}:pause | :resume | :cancel （request_id 必填、幂等）
GET /tasks/{id}/cases?cursor&page_size&status （游标分页，page_size≤500）
GET /tasks/{id}/cases/archive?cursor&page_size&status （归档明细查询，Parquet 游标分页）
GET /tasks/{id}/cases/{cid} （按保留层级读取 DB 或 Parquet）
GET /tasks/{id}/summary （读预聚合，文字+图表数据）
GET /queue/stats （读预聚合，不扫 case_run）

播放：
POST /sources:index （异步建索引）
GET /sources/{id}/channels
GET /sources/{id}/chunk?channel&ts&span
GET /sources/{id}/frame?channel&ts&idx

### 4. 状态机（不可逆约定）
Task : expanding → queued|failed|canceled
       queued → scheduled → running ⇄ paused → queued
       queued|scheduled|running|paused → succeeded|failed|canceled
CaseRun : queued → scheduled → running ⇄ paused
→ succeeded|failed|canceled|timeout|worker_lost
timeout|worker_lost → queued（仅 retry 策略允许且 attempt<retry.max）；否则为终态。

任务在所有 CaseRun 完整展开并校验前必须保持 `expanding`，不得调度。
CaseRun 状态只能由 Scheduler 的状态转换入口写入。展开 Worker 只提交展开批次
及完成/失败事实；执行 Worker 只提交带 `case_run_id + attempt + worker_id` 的启动、
心跳和结果事实。Scheduler 对照当前状态、attempt 和 worker_id 作条件更新；过期
attempt 或已被取消/超时的结果不得覆盖当前状态。API 只持久化带 request_id 的
pause/resume/cancel 控制请求，不直接改状态；Scheduler 幂等消费请求。终态结果经
Scheduler 报告入口提交并携带幂等 report_id；仅在结果
事务提交后确认，重复提交不得重复写结果/预聚合。Task 的执行态由 Scheduler 根据
CaseRun 和展开状态更新。

expanding 状态不接受 pause/resume；cancel 可在展开期间接受，Scheduler 阻止后续展开批次，
并取消已生成的非终态 CaseRun。

暂停仅保证同一 Worker 进程仍存活时保留现场；Worker/Pod 丢失后按 worker_lost
策略从头重跑该 CaseRun，不承诺进程检查点恢复。

Task 状态按以下优先顺序聚合：未完成展开为 expanding；最新已接受且未被后续 resume
覆盖的 pause 请求生效、并且无 scheduled/running CaseRun 时为 paused（queued CaseRun
保留但不派发）；有 running 为 running；否则有 scheduled 为 scheduled；否则有 queued
为 queued；所有 CaseRun 终态时，cancel 请求已接受则为 canceled，全部 succeeded 为
succeeded，否则为 failed。空 Set 不允许提交仿真任务。

### 5. 幂等
task_id / case_run_id 全局唯一。

重复提交同一规范化请求返回既有 task，除非显式 dedup=false。请求指纹必须覆盖
Set snapshot checksum、Scenario 版本及 checksum、Metric 定义版本与 config、
仿真引擎不可变制品标识、规范化 RuntimeConfig 和随机种子；Metrics 按稳定顺序规范化。
`dedup=false` 时不复用任务，但仍记录相同的请求指纹用于追溯。

request_fingerprint = sha256(canonical(snapshot + scenario_versions + metric_configs
  + engine_digest + runtime_config + seed))。

### 6. 规模约定
单任务 cases：几个 ~ 万级。

提交 >500：异步展开（status=expanding），分片批量写（每批 1000）；≤500 时仅在
task、完整 CaseRun 集及 outbox 同一事务提交后返回 queued。

全局 case_run 存量：10万~30万，按月分区，热数据保留 3 个月。

case 级接口：游标分页，page_size ≤ 500，禁止 OFFSET 深翻。

任务列表/结果图表：读预聚合表（task_summary / task_metric_agg）。

场景集：单 Set ≤10000 成员以覆盖单任务万级 cases；≤2000 单文件，>2000 分片（每片 2000）。

### 7. 红线（全部 Agent 遵守，Evaluator 逐条核对）
每轮 logs/round-NNN.log ≤ 1,048,576 bytes，超限由 Scribe 守卫截断记 truncated。

不得改 evals/*.json 与断言抬分。

不得绕过本契约自造字段；契约变更走 schema-bump + migration。

单文件 ≤ 400 行、函数 ≤ 50 行、无调试残留。

长任务异步 + 可暂停 + 可取消 + 可恢复；API 线程禁止阻塞 > 200ms。

调度必须实现优先级 + 老化防饥饿 + 小批量高优插入 + 配额。

单任务 cases 几个~万级、全局 10万~30万：case 级列表必须游标分页（≤500）；
任务列表/结果图表必须读预聚合；case_run/case_result 必须按月分区。

binary 执行：args 模板变量与 env 必须白名单，禁止任意注入。

播放器：按需分片 + seek < 500ms + 多通道同步 + raw-vs-sim 对比。

结果页必须有文字汇总 + ≥2 图表 + 失败下钻 + 播放入口。

空/加载/错误[/索引中] 状态齐全。

不得引入未批准重依赖（见 tech-stack 契约）。

每轮必须产出可复现 evals/round-NNN.md。

已发布且 checksum 校验通过的 Scenario JSON 文件是事实源；DB 投影冲突时据此重建索引。
文件缺失或校验失败时标记版本不可用并告警，不得静默覆盖或继续作为有效快照使用。

case_run 领取必须 FOR UPDATE SKIP LOCKED（或等价原子语义），禁止先查后改。

调度器状态全在 DB，重启可恢复；多副本必须单 leader。

Schema 变更必须走 migration 文件。

生产必须启用认证、project 级授权、审计和数据存储访问控制；无鉴权仅限本地开发与 CI。

引入 MQ/K8s 前必须有瓶颈证据并经 Architect 批准。

Metric 五层：category(固定5类) → type(树形) → template(env_schema)
→ def(规则组合+元信息，(id,version)) → instance(config 规则实例)。
禁止把 template/env_schema 内联进 def；禁止实例只存扁平 params。

Metric 校验两级：先按 def 的规则结构 schema 校验 config 整体
（trigger_functions/functions 数组 + ops + ret + action 等），
再对每个 trigger_functions[i].env / functions[i].env 按 template_id
取 env_schema 动态校验。任一级失败拒绝写入。

ScenarioSet 冻结后不可变，成员锁 scenario_version；展开仿真读冻结快照。

### 8.1 创建场景
1. POST /scenarios → 校验 Pydantic + Metric 两级校验
2. DB 事务：scenario.current_version+=1 + 全量替换 scenario_metric + 写 scenario_version
3. 写文件 scenarios/{id}/v{n}.json（tmp→rename）
4. 回填 file_checksum；失败标 dirty
5. 返回 scenario_id + version

### 8.2 提交仿真任务
1. POST /tasks → 校验 set 已冻结 + runtime 白名单
2. 计算 total_cases（读 Set 元信息）
3. ≤500：同步展开；>5000：status=expanding + 异步展开
4. 展开：流式读 Set 成员 → 批量写 case_run（每批1000）→ 更新 task_summary.total
5. 展开完成置 queued

### 8.3 调度与执行
1. Scheduler.tick：心跳超时回收 → 原子领取（SKIP LOCKED）→ Executor.submit
2. Worker 执行 → 回写 case_run 状态 + case_result + 增量更新 task_summary/task_metric_agg
3. 每 30s 对账

## 9 失败与补偿：
| 场景 | 行为 |
|---|---|
| Metric 校验失败 | 400 METRIC_CONFIG_INVALID，事务回滚，不写文件 |
| 文件写失败（DB 已提交） | 标 dirty，后台重建，返回 202 + 警告 |
| 展开失败 | task.status=failed，记录 reason，已写 case_run 保留（可重试续传） |
| Executor.submit 失败 | case_run 回 queued，attempt+=1，超 retry_max 置 failed |
| 心跳超时 | worker_lost → queued（attempt<retry_max）或 failed |