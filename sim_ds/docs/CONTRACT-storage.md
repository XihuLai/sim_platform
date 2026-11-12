# Storage Contract v2.0
> Architect 维护。DDL 变更走 migrations/；同一主版本仅允许向后兼容新增，
> 破坏性 schema 变更须升主版本并提供数据迁移/回滚说明。
> v2.0（BREAKING）：定义不可变版本文件发布/修复协议、展开幂等键、分区归档查询和复现清单；
> migration 004 更换任务去重约束并引入资源预留。
> v1.1：case_run/case_result 改月分区；新增 task_summary/task_metric_agg/
> task_expand_cursor；Set 成员分片；场景 Metric 改五层模型。
> DDL 见 migrations/001_init.sql–004_scheduler_integrity.sql，本文件为规范说明。

## 1. 文件与 DB 分工

| 内容 | 存哪 | 理由 |
|---|---|---|
| 完整 Scenario JSON | 文件 scenarios/{id}/v{n}.json | 事实源，可 diff/回滚 |
| 可查询维度 | DB scenario 表 | 列表筛选/聚合 |
| 扩展字段 | DB extra JSONB + JSON 内 extra | 新增字段不改表 |
| Set 版本快照 | 文件 sets/{id}/v{n}.json（>2000 分片） | 冻结可复现 |
| 分类/类型/定义 | DB metric_category/type/def | 全局一致 |
| 场景实例 | DB scenario_metric + JSON .metrics[] | DB 为可查询投影；JSON 为事实源 |
| 大 artifact/点云/视频 | 文件/对象存储 | DB 不存大数据 |

一致性：DB 行存 file_uri + file_checksum(sha256)。已发布的版本文件不可变，是 Scenario、
Set 和实例 Metric 配置的内容事实源；DB 是版本生命周期、当前指针和可查询维度的索引。
仅有 DB `publish_state=published` 的版本才可被引用；未知孤儿文件不得自动成为当前版本。
checksum 错误或文件缺失时必须标记版本不可用并告警，不得把损坏内容当作新事实源。
`publish_state` 取值：pending（发布中）、published（可引用）、failed（首次发布失败）、
unavailable（已发布文件缺失或校验失败）；unavailable 仅在文件恢复且 checksum 匹配后
恢复为 published。

### 1.1 版本文件发布与恢复

1. 每次编辑生成新版本，不覆盖已发布版本。先在短 DB 事务中插入
   `publish_state=pending` 的版本意图、expected_version 和 checksum，再将完整内容写入
   同存储域临时对象；校验 schema/checksum 后不可变发布文件，最后在短 DB 事务中置
   `published` 并更新当前版本指针/索引。文件 I/O 不得占用 DB 长事务。
2. POSIX 同文件系统使用 fsync + 原子 rename；NFS/对象存储按其保证使用条件写或不可变
   对象策略，禁止假设跨存储域原子 rename。临时对象使用由实体 ID+版本号确定的稳定 URI，
   必须能在进程重启后恢复发布。
3. 并发编辑使用 expected_version 条件更新；版本意图冲突返回 409。version 号不回滚，
   同一版本号/校验和的重试幂等；failed 仅可用相同 checksum 重开为 pending，校验和不同
   则拒绝并要求创建后续版本。
4. 崩溃恢复：pending 且 final 文件 checksum 匹配 → 完成 DB publish；仅有有效临时文件
   → 重试发布后完成 DB publish；两者都不存在/校验失败 → 标记 failed、告警并要求重试，
   不得切换当前指针。已发布文件但 DB 最终事务失败时，按 pending 意图安全续做。
5. 冻结 Set 仅在快照和全部分片发布、清单总 checksum 校验通过后置 frozen；冻结后版本
   不可变。巡检只从 published 且校验通过的版本修复投影；已运行任务不改写快照。

## 2. ScenarioSet 存放规范

1. 事实源：/data/sets/{set_id}/v{n}.json，冻结后不可变。
   >2000 成员分片：v{n}.meta.json（清单+总 checksum）+ v{n}.members.{k}.json
   （每片 2000）。
2. DB：scenario_set（元信息）、scenario_set_version（快照指针+sha）、
   scenario_set_member（成员，按 (set_id,set_version) 隔离）。
3. 成员必须锁定 scenario_version，禁止"取最新"。
4. 写入时序：未冻结编辑 → 事务先写 pending version 行及全量成员 → 发布 version+1
   文件/分片 → 事务置 published 并更新当前版本指针；进程崩溃按 1.1 节恢复。每个发布
   版本文件均不可变。
5. 冻结不修改已发布文件：基于当前未冻结版本创建 version+1 的冻结快照（复制并锁定
   成员），登记 pending 意图，发布 `frozen=true` 文件/分片，再在 DB 同一事务置
   publish_state=published、写 frozen_at 并更新 current_version/frozen。DB 最终事务失败时
   Set 仍未冻结，按 pending 意图重试；冻结后成员变更一律 409，只能 derive 新 Set。
6. 仿真展开 CaseRun 必须读取 `frozen_at` 非空的冻结版本文件，并以 snapshot_sha 校验。
7. 巡检：验证 snapshot_sha 与已发布文件 checksum_self；校验通过的文件可修复 DB 成员
   投影，文件缺失或校验失败时将版本标记不可用并告警。
8. 规模：单 Set ≤10000 成员以覆盖单任务万级 cases；>2000 分片；DB 批量写；接口游标分页；
   展开流式 COPY。
9. 场景归档不阻断已冻结 Set 读取；新建/编辑 Set 禁止加入 archived 场景；
   场景硬删前必须检查冻结 Set 引用。

## 3. Metric 五层规范

### 3.1 五层模型
metric_category（固定 5 类：comfort/compliance/safety/efficiency/navigation）
└── metric_type（树形细分，parent_id）
└── metric_template（template_id，kind=trigger|function，env_schema）
└── metric_def（(id,version)，规则组合+元信息）
└── scenario_metric（config 规则实例）


### 3.2 metric_template（新增层）
- 承载 template_id（"9"/"30"/"27"...）与 env_schema（JSON Schema）。
- kind：`trigger`（时间区间/事件）或 `function`（急刹/车道保持/画龙）。
- env_schema 定义 env 字段结构（field_name/is_number/unit/value 等）。
- 新增 template 只插一行，不改表；废弃用 status=deprecated（建议加该列）。

### 3.3 metric_def
- 主键 (id, version)；schema 不兼容变更 version+1；direction 无关（规则表达式
  已含 ret）；删除禁止，用 status=deprecated。
- 元信息：level（S0/S1/S2）、business_type（dpc...）、run_mode（async/sync）、
  is_global。
- 规则组合：trigger_templates、trigger_ops、function_templates、ops、
  ret、action。只引用 template_id，不存实际 env 值。

### 3.4 scenario_metric
- 字段：scenario_id、metric_def_id、metric_def_ver、alias、config JSONB、
  enabled、extra。
- config 存完整规则实例：
  { trigger_functions[], trigger_ops[], functions[], ops[], ret, action,
    level, is_global }。
- 同一场景同一 def 可配多组（alias 区分）。
- 复现：仿真展开按 JSON 的 metric_def_ver 取定义，禁止取最新版。

### 3.5 两级校验
1. **结构校验**：按 def 的规则结构 schema 校验 config 整体
   （trigger_functions/functions 数组、每项必须有 template_id+env、
   ops 枚举 AND/OR、ret 枚举 pass/fail、action 字符串、level 枚举等）。
2. **动态校验**：对每个 trigger_functions[i].env 与 functions[i].env，
   按 template_id 查 metric_template.env_schema 校验 env。
3. 任一级失败拒绝写入，返回字段路径 + 原因（code=METRIC_CONFIG_INVALID）。
4. template_id 必须存在于 metric_template 且 kind 匹配
   （trigger_functions 用 kind=trigger；functions 用 kind=function）。
5. metric_def 的 trigger_templates/function_templates 声明的 template_id
   必须在 config 中出现（required=true 时）。

### 3.6 写入与复现
- 写入：Metric 配置先随 pending Scenario 版本意图和 DB 投影写入事务保存，再发布新
  Scenario JSON 文件，最后置 published 并更新当前版本指针；DB/文件失败按 1.1 节恢复。
- 复现：仿真展开按 JSON 的 metric_def_ver 取定义；env 值以 JSON 为准。
- 巡检：校验 DB config 与 JSON .metrics[]；只从 checksum 校验通过的已发布版本修复投影。

### 3.7 规模
- 分组查询 join 五表禁 N+1；写入批量；config 单行 ≤16KB（超限拆 alias）。
- 分类/类型/模板/定义进程内 TTL 缓存（60s），变更后失效。
- 按 template_id 反查场景：`scenario_metric.config @> '{"functions":[{"template_id":"30"}]}'`
  走 GIN 索引（idx_scn_metric_cfg）。

## 4. 大表分区与预聚合

1. case_run / case_result：PARTITION BY RANGE (created_at) 按月分区；任何分区表
   PRIMARY KEY/UNIQUE 必须包含分区键。case_run 用 (id, created_at) 作物理主键；
   同一 task 的异步展开写入使用 task_expand_cursor.case_run_created_at 固定时间，
   新增唯一约束 (task_id, scenario_id, created_at)，避免断点重试重复创建 CaseRun。
2. case_result 以 case_run_id/task_id 逻辑关联，不建立跨分区外键；写入按 run id、
   task id、attempt 校验归属，巡检检测孤儿结果。
3. 调度热索引只在活跃分区。
4. task_summary / task_metric_agg 预聚合，增量更新 + 30s 对账。
5. 仅当分区内没有非终态 CaseRun，且其完成数据已超过 3 个月，才 DETACH 归档 Parquet；
   长期运行或排队任务会延长所在分区保留期。导出需可重试、幂等并校验行数和 checksum，
   校验通过后才允许删除分区。归档后 CaseRun/结果明细由
   `GET /tasks/{id}/cases/archive` 游标接口读取，按 ID 的详情接口查询 DB 或归档层；
   不能宣称 DB 仍提供 case 级历史下钻。
6. 同一任务全部异步展开（>500 cases）保持 expanding；task_expand_cursor 保存固定的
   case_run_created_at 并断点续传。
7. 迁移 004（新建，不改写 001~003）新增版本发布状态、request_fingerprint/dedup_enabled、
   资源预留/Task 控制请求表、展开时间戳、结果 attempt/report ID、CaseRun 展开幂等唯一索引，
   并按执行日期引导创建当前月及未来 3 个月分区；迁移需
   预检重复记录并说明前向恢复方式。
   迁移前已存在的 Task 没有完整 v2 指纹，标记 dedup disabled，不参与新请求去重。

## 5. 灵活性原则

1. extra JSONB 兜底：新字段先放 extra，高频筛选才升为列。
2. 标签两维演化：category 横切 + parent_id 树形。
3. Metric 五层：template 承载 env_schema，def 承载规则组合，instance 承载实例。
4. 版本快照落文件：version 表只存指针 + checksum。
5. task 固定 Set snapshot checksum、Scenario 版本/checksum、Metric 定义版本与 config、
   引擎制品 digest、规范化 RuntimeConfig 和 seed；request_fingerprint 覆盖这些输入。

## 6. SQLite 降级（仅开发）

JSONB→JSON（json_extract 表达式索引）；TIMESTAMPTZ→TEXT/INTEGER；
BIGSERIAL→INTEGER PK AUTOINCREMENT；分区降级为普通表；
不支持 SKIP LOCKED / advisory lock → 调度模块检测到 SQLite 必须报错退出。

## 7. 规范

- Scenario JSON 用 Pydantic v2 校验；metric config 用两级 JSON Schema 校验。
- 不引入 proto 作为事实源；若引擎需要 proto，在 backend/sim/adapters/
  做 JSON→proto 适配层。
- 单行 JSONB ≤ 64KB；scenario_metric.config ≤ 16KB。
- 归档路径：/data/archive/{yyyy-mm}/；artifact 30 天后转对象存储。
- 新增/变更 DDL 使用 migrations/004_*.sql；旧迁移保持不可变。迁移失败时恢复至
  变更前 schema；迁移完成后若已有 dedup=false 任务，不保证可逆删除，只能先解决重复
  (set_id, set_version, runtime_hash, metrics) 键再重建旧唯一约束。
- migration 004 是 v2.0 协调升级：执行前停止 v1 写入，校验既有 Scenario/Set 文件 checksum
  并预检 CaseRun 展开重复；先完成所有 v1 expanding 任务，不能完成的需显式终止并重新提交。
  任一检查失败先修复再迁移。迁移完成并部署 v2.0 服务后才恢复写入，不支持 v1/v2 混跑。
