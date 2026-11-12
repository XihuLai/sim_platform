# SimCloud 架构说明

## 1. 分层

```text
React 10 页
  API layer (frontend/app/src/api.ts)
        │  /api
FastAPI routers / deps / auth / audit
        │
Domain services
  ScenarioService ── ScenarioSupport ── FileStore
  SetService      ── SetSupport      ── snapshot builder/sharding
  MetricService
  TaskService     ── TaskReadMixin
  Expander / Scheduler / LocalExecutor / ResultService + AggregateMixin
  PlaybackService ── synth payloads + FileStore
        │
PostgreSQL 15+ (raw SQL, JSONB, SKIP LOCKED, partitions, preaggregates)
File system (Scenario/Set JSON, playback index/chunks, outputs)
```

- 文件是 Scenario、Set 和 Metric 实例的**内容事实源**；DB 保存版本意图、当前指针、
  URI、checksum 和可查询投影。
- DB 行只有 `publish_state=published` 才能被业务读取；`pending/failed/unavailable`
  不允许被任务引用。
- 后端所有路径避免长 DB 事务内做文件 I/O。

## 2. 版本发布与恢复

1. 短事务写入 `pending` 版本意图（含 `expected_version`、checksum）和投影。
2. 写入稳定临时对象 `*.tmp`，fsync 后 `os.replace` 原子发布最终文件。
3. 短事务校验 checksum，置 `published`，条件更新当前版本指针
   `WHERE current_version=expected`；并发编辑返回 409，不回滚版本号。
4. 启动时重新扫描 `pending`：最终文件有效 → 完成发布；稳定临时文件有效 → 提升后完成；
   均失败 → 标记 `failed`，不切换当前指针。
5. Set 冻结使用 `version+1` 的新快照，冻结文件发布成功后才写 `frozen_at` 与
   `scenario_set.frozen`；恢复逻辑会补齐 `frozen_at`。
6. 读取时 checksum 失败：Scenario/Set 返回 `VERSION_UNAVAILABLE`，Scenario 同步标记
   `unavailable`，等待文件修复后人工恢复。

## 3. Metric 五层

```text
metric_category (固定 5)
└─ metric_type (parent_id 树)
   └─ metric_template (kind=trigger|function, env_schema)
      └─ metric_def ((id,version), 规则组合)
         └─ scenario_metric (config 实例, alias 区分多组)
```

场景写入时先做结构校验（必需数组、template_id、env、ops/ret/level），再按
`metric_template.env_schema` 做 JSON Schema 动态校验。定义中的 required 模板必须在
实例 config 中出现。所有校验失败返回字段路径。

## 4. 任务展开与调度

### 展开
- `TaskService.submit` 读取冻结 Set 快照，按 `max_cases` 收敛 expected。
- `expected ≤ 500`：单事务创建 `sim_task` + `task_summary` + 全部 CaseRun + outbox。
- `expected > 500`：任务状态 `expanding`，写 `task_expand_cursor`（固定
  `case_run_created_at`），由 `Expander` 按最多 1000/批插入。
- 唯一键 `(task_id, scenario_id, created_at)` 保证断点重试不重复创建。
- 每批完成后从 `case_run` 实际状态重算 `task_summary`，避免“插入了 cases 但游标未推进”
  的崩溃窗口。
- 全部展开后校验实际数量 = expected，再切换为 `queued`。

### 调度
- 仅 PostgreSQL；启动时通过 advisory lock 选出单一 leader。
- `claim` 使用 `FOR UPDATE SKIP LOCKED`，同时校验 project quota、worker capacity、
  高优先级保留位与暂停请求。
- 排序使用 `priority - wait_seconds/aging`，实现老化防饥饿。
- 选中 case 后置 `scheduled`，写 `resource_reservation` 与 outbox；
  预留键 `(case_run_id, attempt)` 幂等。
- 派发只读 outbox，不把 MQ 当状态源。

### 执行与结果
- `LocalExecutor` 使用独立进程组启动 `python -m backend.sim.engine_cli`，环境变量与
  args 模板变量走白名单。
- 心跳每 10s；超时杀进程组。`ResultService` 以 `(case_run_id, attempt, report_id)`
  处理重复/过期报告。
- 失败按 RuntimeConfig.retry 重排；每次状态迁移同时更新 `task_summary`、
  `case_result`、`task_metric_agg`，并只释放一次资源预留。
- 30s 对账 `reconcile` 从 CaseRun 重算计数与 pass/fail；`recompute_p95` 更新指标 p95。
- Task 终态由纯函数 `derive_task_status` 判定，便于单元测试。

## 5. 规模与读模型

- `case_run` / `case_result` 按月分区；主键包含分区键。
- 任务列表、队列、结果摘要读 `task_summary` / `task_metric_agg`，不扫明细。
- case 列表、Set 成员、任务/场景/数据源列表全部使用 `(排序键,id)` 游标，
  禁止 OFFSET 深翻页；case 每页上限 500。
- 归档只在分区无非终态 CaseRun 且完成时间超过 3 个月后导出 Parquet；
  `/tasks/{id}/cases/archive` 提供游标读取，详情接口可回落到归档层。

## 6. 安全与隔离

- 生产模式必须 `SIM_AUTH_MODE=required` 且配置至少一个 token，否则启动失败。
- 请求 principal 绑定 `project`；所有服务查询显式带 `project` 条件。
- 跨项目读取返回 404（避免泄露存在性）；写入越权返回 403。
- 关键写操作写 `audit_log`；`/audit` 按项目游标读取。

## 7. 前端

`frontend/app` 使用 React Router，页面：场景列表/创建/编辑、Metric、场景集、发起仿真、
任务列表、队列看板、任务详情、结果汇总、播放器。列表使用自研虚拟滚动 + 游标
“加载更多”；结果页含环形图与柱状图；播放器支持单路/对比、时间轴 seek、多通道切换、
video SVG / pointcloud / timeseries 渲染。所有页面具备空/加载/错误状态，播放器另有
索引中状态。

## 8. 已知取舍

- LocalExecutor 为单机起步实现；生产 K8sPool/K8sJob 可在 `Executor` 接口后替换。
- mcap/bag 解析适配器目前用 manifest 元数据桩，chunk 数据为确定性合成数据。
- 归档查询需可选依赖 `pyarrow`；未安装时返回 503，不影响主链路。
