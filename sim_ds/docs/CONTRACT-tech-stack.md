# Backend Tech Stack Contract v2.0
> Architect 维护，所有后端 Agent 只读。
> 与 CONTRACT.md 冲突时：业务语义以 CONTRACT.md 为准，技术选型以本文件为准。
> v2.0（BREAKING）：补充 PostgreSQL CI 集成测试、生产项目隔离、暂停故障语义、
> 版本文件发布协议与性能验收负载记录。

## 0. 总则

1. 事实源唯一性：文件系统是场景定义事实源；DB 是索引与调度状态事实源；
   MQ 永不作为状态源。
2. 依赖最小化：新增运行时依赖必须在 CHANGELOG 记录版本/理由/替代方案，
   经 Architect 批准。
3. 可降级：可移植单测不得依赖 K8s/MQ/PostgreSQL；CI 必须另含 PostgreSQL 集成测试，
   覆盖 SKIP LOCKED、分区、索引、事务和并发语义。SQLite 不作为这些行为的替代验证。
4. 可测试：调度决策逻辑必须能在无 K8s、无 MQ、单进程内单测。
5. 可恢复：任何后端进程重启后必须能从 DB + 文件恢复全部状态。

## 1. 语言与运行时

| 项 | 选型 | 约束 |
|---|---|---|
| 语言 | Python 3.12（基线）；3.11（CI 降级兼容） |
| 约束 | 基线用 3.12 语法；CI 必须同时跑 3.11，确保降级可用 
| 包管理 | uv（或 pip-tools） | requirements.txt + 锁定文件 |
| lint/format | ruff | warning 即失败 |
| 类型 | mypy --strict（核心模块） | 调度域、契约模型必须 strict |
| 测试 | pytest + pytest-asyncio | 关键路径 ≥ 80% |

## 2. Web 与 API

| 项 | 选型 | 约束 |
|---|---|---|
| 框架 | FastAPI | 必须声明 response_model |
| 校验 | Pydantic v2 | Metric params_schema 用 JSON Schema |
| 异步 | asyncio | API 线程禁阻塞 > 200ms |
| 错误 | {code, message, detail} | 禁止裸 HTTPException 无 code |
| 分页 | 游标（keyset）为主 | case 级 page_size≤500；任务/Set 列表游标 |
| 鉴权 | 本地开发/CI 可无 | 生产必须认证、project 级授权、审计；存储层也须实施访问控制 |

## 3. 存储分层

| 层 | 技术 | 存什么 | 禁存什么 |
|---|---|---|---|
| 事实源 | 文件系统（生产可 NFS/对象存储） | Scenario/Set JSON、artifact、索引、输出 | — |
| 索引/状态 | PostgreSQL 15+ | 场景/指标/Set 索引与发布状态、task/case_run、worker、配额/资源预留、控制请求、outbox、预聚合 | 大 JSON 全文、artifact、点云、视频 |
| 开发降级 | SQLite | 仅本地开发/CI | 禁止作为调度事实源 |
| 缓存 | 首轮不引入 Redis | — | 禁止当状态源/队列事实源 |

文件布局（冻结）：
/data/scenarios/{id}/v{n}.json
/data/sets/{id}/v{n}.json            （>2000 成员分片：v{n}.meta.json + v{n}.members.{k}.json）
/data/sources/{id}/index.json + chunks/
/data/outputs/{task_id}/{case_run_id}/
/data/logs/{task_id}/{case_run_id}.log
/data/archive/{yyyy-mm}/...          （DETACH 后的 Parquet）

DB 硬约束：
- 生产必须 PostgreSQL（SKIP LOCKED、JSONB+GIN、advisory lock、部分索引、分区）。
- SQLite 仅开发；调度模块检测到 SQLite 必须显式报错退出。
- DDL 走 migrations/NNN_*.sql；同一主版本仅允许向后兼容新增，破坏性 schema 变更须升主版本并提供数据迁移/回滚说明。
- 单行 JSONB ≤ 64KB；超限落文件，DB 存 uri+checksum。
- DB 存 file_uri + checksum；仅从已发布且 checksum 校验通过的文件重建索引。
- Scenario/Set 版本文件一经发布即不可变。先以短 DB 事务登记 pending 版本意图，再写
  同存储域临时对象、校验 checksum 并发布，最后以短事务置 published 并更新当前指针。
  对象存储使用条件创建或等价不可变发布，不假设 rename 原子。
- pending 意图允许在崩溃后续做；DB 引用的已发布文件缺失或 checksum 不符时标记不可用
  并告警，不得静默重建成“成功”。未冻结编辑也必须版本化发布，冻结 Set 仅在文件发布
  成功并校验后置 frozen。

## 4. 调度与执行

派发通道：
- 默认：DB FOR UPDATE SKIP LOCKED。
- 可选：MQ（Redis Stream / RabbitMQ / Kafka，Architect 三选一），
  仅当派发 P95 > 1s 或吞吐 < 100 case/s，需瓶颈证据 + 批准。
- MQ 纪律：outbox + relay + 幂等消费；MQ 只传派发通知，不传状态；
  Worker 结果经 Scheduler 报告入口落库，MQ 不作为结果或状态通道。

Executor 抽象（可插拔）：
  submit / pause（保留现场）/ resume / cancel（终止进程树）/ status

| 实现 | 定位 | 暂停 | 取消 |
|---|---|---|---|
| LocalExecutor | 开发/CI/单机 | SIGSTOP 进程组；仅同进程存活时保留现场 | SIGTERM→SIGKILL |
| K8sPoolExecutor | 生产主路径（1 task:N case:M pod，M<<N，每 pod 多 slot） | worker 内 SIGSTOP 子进程；Pod/Worker 丢失后从头重跑 | 杀进程树 + 回写 |
| K8sJobExecutor | 仅强隔离兜底 | 不支持原地暂停 | kubectl delete job |

Executor 不变量（任何实现必须满足）：
1. CaseRun 状态/结果只由 Scheduler 状态转换入口提交到 DB；Executor/Worker 上报带
   attempt 与 worker_id 的事实及心跳，不直接改变状态。
2. 派发走 outbox，状态变更与派发消息同事务。
3. 消费幂等：running 转换带 status 前置条件。
4. 暂停仅在原 Worker 进程存活期间保留现场；Worker/Pod 丢失后按 worker_lost 策略重跑。
   取消=终止进程树；抢占粒度=CaseRun 级。
5. 心跳超时可被调度器回收重试（仅 timeout/worker_lost）。

调度器：
- 自研，单 leader（pg_advisory_lock 或 K8s lease）。
- 状态全在 DB，重启 10s 内续跑。
- 老化：读取时计算 effective_priority（禁止每 tick 全表 UPDATE）。
- 抢占：高优排队且槽位被低优占用 → 暂停低优 CaseRun（非 kill）。
- 领取：FOR UPDATE SKIP LOCKED，小批量高频（20~100/tick）。
- 派发短事务，避免长事务锁。
- 结果回写增量更新 task_summary / task_metric_agg。
- 配额与 Worker 资源须在领取时原子预留；预留以 (case_run_id, attempt) 幂等，
  终态/失联回收时恰好释放一次，调度器重启后对账并修复孤儿预留。

K8s 边界：
- K8s 管：pod 副本/资源/亲和/弹性/Pod 级驱逐兜底。
- 应用层管：case 优先级/老化/配额/CaseRun 级抢占/暂停恢复/状态机。
- PriorityClass 只作节点资源不足时驱逐低优 worker pod 的兜底，
  不作 case 级优先级。

## 5. 排除的重依赖

| 依赖 | 状态 |
|---|---|
| Celery | ❌ |
| Redis 作状态源/队列事实源 | ❌ |
| DB 存大对象 | ❌ |
| 每 case 一 Job 作批量主路径 | ❌ |
| 运行时 CREATE TABLE / schema 漂移 | ❌ |
| Ray/Volcano/Argo 等 | ⚠️ 需批准，且不得绕开 Executor 接口与 DB 状态机 |

## 6. 非功能指标

| 指标 | 目标 |
|---|---|
| 单任务 cases | 几个 ~ 万级（>500 异步展开） |
| 全局 case_run 存量 | 10万~30万（按月分区，热 3 个月） |
| 高优调度延迟 queued→running | P95 < 1s |
| 常规调度延迟 | P95 < 5s |
| 派发吞吐 | ≥ 100 case/s |
| 暂停生效 | < 2s |
| 取消生效 | < 5s |
| 调度器重启恢复 | 10s 内 |
| 提交接口 P95 | < 1s（>500 异步展开） |
| case 列表接口 P95 | < 300ms（游标 + 分区裁剪） |
| 任务列表 P95 | < 200ms（读 task_summary） |
| 结果图表接口 P95 | < 300ms（读预聚合） |
| 并发领取正确性 | 零重复、零丢失 |
| 每轮日志 | ≤ 1,048,576 bytes |

性能验收必须同时记录可复现负载画像：PostgreSQL/Worker/Pod 规格与数量、并发任务数、
CaseRun 时长分布、冷/热启动比例、运行时长、故障注入比例、数据集规模、采样与 P95
计算口径。没有该画像的指标仅作目标，不视为通过。
暂停时限只适用于声明支持 pause 的 Executor；不支持的 Executor 必须在接受控制请求前
明确拒绝，不得返回成功形状或把 Task 标成 paused。

## 7. 分区与归档

- case_run / case_result：PARTITION BY RANGE (created_at)，按月分区，
  提前建 3 个月 + 定时建下月。
- 调度热索引仅在活跃分区（部分索引 status IN queued/scheduled）。
- 完成态数据保留 3 个月热分区；到期 DETACH 导出 Parquet 到
  /data/archive/{yyyy-mm}/，DB 仅保留 task_summary/task_metric_agg。
- case_run 的扩展幂等键为 (task_id, scenario_id, created_at)，其中 created_at
  对同一任务展开固定不变；该键与分区键兼容。分区表主键/唯一约束必须包含 created_at。
- case_result 不建立指向分区 case_run 的跨表外键；以 (case_run_id, task_id) 逻辑关联，
  写入时校验 attempt/run 归属，巡检负责孤儿检测。
- 归档导出需可重试且幂等；导出校验和、行数及目标对象校验通过后才允许删除分区。
  历史 case 级查询须经归档查询入口支持；保留期内 DB 查询，归档后从 Parquet 查询。
- artifact：DB 只留 output_uri；最近 30 天本地，之后转对象存储。
- task_summary / task_metric_agg：永久保留（体量小）。

## 8. 变更流程

1. 提 docs/proposals/tech-stack-R{round}.md（动机/影响/替代/回滚）。
2. Architect 评审；破坏性变更开新主版本并在 CHANGELOG 高亮。
3. 通过后更新本文件 + migrations/ + 通知全部 Agent。
4. Evaluator 在"契约一致性"核对实现与本文件。

## 9. 一句话摘要

FastAPI + Pydantic v2 + PostgreSQL 15（索引/调度状态/预聚合，生产强制；
SQLite 仅用于便携开发测试，PostgreSQL CI 集成测试覆盖生产语义）
+ 文件系统（不可变版本文件为场景/Set 事实源，DB 存 uri+checksum）
+ 可插拔 Executor（Local 起步，K8sPool 生产主路径，K8sJob 兜底）
+ DB SKIP LOCKED 派发（MQ 可选加速，outbox+幂等，永不作为状态源）
+ 调度单 leader、状态全在 DB、重启可恢复 + case_run/case_result 月分区
+ 预聚合（task_summary/task_metric_agg）+ 游标分页适配 10万~30万规模。