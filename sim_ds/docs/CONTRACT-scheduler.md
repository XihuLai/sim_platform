# Scheduler Contract v2.0
> Architect 维护。
> v2.0（BREAKING）：所有异步展开使用 expanding；明确状态转换入口与 Worker 报告、
> 资源预留、暂停故障恢复及复现指纹。
> v1.1：适配 10万~30万 case_run；老化改读取时计算；异步展开；
> 预聚合回写；抢占限定范围；游标分页。

## 1. 分层

Submit API → 持久化请求 + expanding（或 ≤500 全量原子展开后 queued）
          → Expander 写幂等批次/游标 → Scheduler 校验完成并转 queued
          → Scheduler(单 leader) 决策 → Executor 派发
          → Worker 提交启动/心跳/结果事实 → Scheduler 条件迁移状态
                        → 增量更新 task_summary / task_metric_agg
          → 聚合 API（读预聚合）

## 2. 状态机

Task    : expanding → queued → scheduled → running ⇄ paused
          → succeeded|failed|canceled
CaseRun : queued → scheduled → running ⇄ paused
          → succeeded|failed|canceled|timeout|worker_lost
          timeout|worker_lost → queued（仅 retry 策略允许且 attempt<retry.max）

状态写入仅通过 Scheduler 状态转换入口。Expander 和 Worker 只能提交事实/请求，
不得直接更新 Task 或 CaseRun 状态；API 将带 request_id 的 pause/resume/cancel 请求
写入 task_control_request。Scheduler 必须使用状态、attempt、worker_id 前置条件执行
原子更新，并幂等消费控制请求。

pause/resume 在 expanding 或终态任务上拒绝；cancel 可作用于任一非终态任务，包括
expanding。取消展开时 Expander 每批写入前重读 Task 状态，停止新增 CaseRun；Scheduler
取消已展开的非终态 CaseRun。Task 在所有 CaseRun 终止后进入 canceled。
pause 仅在所有 active CaseRun 的 Executor 都支持原地暂停时接受；否则整条 Task 请求以
明确错误拒绝，不允许部分暂停。抢占只选择支持 pause 的 victim。

## 3. 提交与展开

| 规模 | 路径 |
|---|---|
| ≤500 | 同步：写 task + 全部 case_run + outbox，同一事务提交后置 queued 并返回 |
| >500 | 写 task(expanding)，异步分片展开（每批 1000），返回 task_id |

- 同步展开使用 `sim_task.created_at` 作为所有 CaseRun 的 `created_at`；请求重试通过
  `request_fingerprint` 命中原 task，不重建 CaseRun。
- 展开 Worker 流式读冻结 Set 成员文件，并校验 snapshot_sha。每个任务使用固定的
  `task_expand_cursor.case_run_created_at` 作为所有展开 CaseRun 的 `created_at`，保证
  断点重试落入同一分区；更新 task_summary.total；游标与批次在同一事务提交。
- 展开按 `(sort_order, scenario_id)` 稳定排序；`batch.max_cases=0` 表示全部成员，
  否则取前 max_cases 个。Scheduler 校验 CaseRun 数与预期展开数
  `min(member_count, max_cases)`（max_cases=0 时为 member_count）一致，再转 queued；
  失败由 Scheduler 置 failed 并记录原因。展开 Worker 不直接变更状态。
- `batch.max_cases` 必须为非负整数；请求选择数为 0 或超过 Set 成员数时按上述规则处理。
- 幂等唯一键 `(task_id, scenario_id, created_at)`；扩展写入使用 `ON CONFLICT`/等价幂等
  操作并与游标推进同事务，不先清理已成功批次。前提是同一 Set 版本中 scenario_id 唯一。
- 空 Set 提交返回校验错误，不创建无 CaseRun 的任务。

## 4. 调度循环（每 tick，小批量高频）

1) 心跳超时回收：running/paused 且 heartbeat_at 过期时，按当前 attempt 原子转换为
   worker_lost/timeout；若 attempt<retry.max，再进入 queued 并 attempt+1，否则保持终态。
2) 原子领取（老化在 ORDER BY 内计算，不物化全表）：
   UPDATE case_run SET status='scheduled', worker_id=$1
   WHERE id IN (
     SELECT id FROM case_run
     WHERE status='queued' AND quota_ok(...) AND resource_ok(...)
     ORDER BY GREATEST(0, priority -
                FLOOR(EXTRACT(EPOCH FROM now()-waiting_since)/:aging_sec)),
              waiting_since
     LIMIT :batch FOR UPDATE SKIP LOCKED)
   RETURNING *
   batch 取 20~100；派发短事务。
3) 抢占：仅在同 project 或 running 集合内选最低优 victim（走 running 部分索引），
   Executor.pause(victim)（非 kill）。
4) 派发节流：每 tick ≤ batch；吞吐靠 tick 频率。
5) effective_priority 仅作观测列，可对 waiting_since<now()-aging_sec 的行
   做增量更新，禁止每 tick 全表 UPDATE。

## 5. Executor 契约

Protocol:
  submit(case_run, runtime) -> None
  pause(run_id) -> None            # 同一进程存活期间保留现场
  resume(run_id) -> None
  cancel(run_id) -> None           # 终止进程树 + 释放槽位
  status(run_id) -> CaseStatus

能力矩阵：
| 后端 | 暂停 | 取消 | 适用 |
|---|---|---|---|
| LocalExecutor | SIGSTOP 进程组 | SIGTERM→SIGKILL | 开发/CI/单机 |
| K8sPoolExecutor | worker 内 SIGSTOP 子进程 | 杀进程树 + 回写 | 常驻 Worker Pool；每 Pod 默认一个并发 slot |

远程 Worker 部署约定：
- K8sPoolExecutor 管理常驻 Worker Deployment；Worker 经 Scheduler 的 Bearer Token API
  claim 当前 attempt 的 DB outbox dispatch 项，不直连 DB。
- Scenario 版本、Binary 和输出均在 S3-compatible object store；Worker 使用 SDK 下载
  Scenario/Binary、校验 SHA-256、上传输出，不挂载 PVC。Binary URI 使用
  `RuntimeConfig.binary_uri=s3://bucket/key`，并要求 `binary_checksum`。
- Worker 通过 start/heartbeat/result API 上报事实；Scheduler 校验
  `(case_run_id, attempt, worker_id)` 并在事务中变更 CaseRun/聚合。Worker 无 DB 凭据。
- Worker callback Token、S3 凭据和镜像拉取凭据通过 Secret 注入。Scheduler 的
  Kubernetes ServiceAccount/RBAC 与 Worker ServiceAccount 权限分离。
- 测试与生产分别部署 Backend/Scheduler 和 PostgreSQL，使用不同的 K8s namespace、
  Pool/Deployment 名、Worker Secret/Token、Scheduler URL 及对象存储 bucket/prefix。
  测试 Worker 只连接测试 Scheduler；不可让两套 Scheduler 共用数据库/outbox，否则任务
  可能被错误环境的 Worker 领取。`SIM_K8S_WORKER_SLOTS` 默认 1；Pool 的总并发为
  `SIM_K8S_POOL_REPLICAS × SIM_K8S_WORKER_SLOTS`。

不变量：
1. CaseRun 状态只由 Scheduler 状态转换入口在 DB 变更。Worker 事实带 attempt 和
   worker_id；终态结果另带 report_id。Worker 通过 Scheduler 报告入口提交，不直接写 DB；
   入口只在事务提交后确认结果，未收到确认时可用同一 report_id 重试。重复已提交结果
   返回已提交状态且不重复聚合；旧 attempt 或状态不匹配的迟到报告作为 stale 拒绝。
   启动/心跳按 (case_run_id, attempt, worker_id) 幂等。
2. `queued → scheduled`、资源预留和 outbox 插入同一事务提交；outbox relay 只负责
   通知，消息投递失败可重试，不改变 DB 状态事实。
3. 消费幂等：scheduled → running 与报告处理均带状态前置条件；影响行数为 0 或
   attempt/worker 不匹配时报告为 stale，不得覆盖当前状态。
4. 暂停仅保证原 Worker 进程存活期间保留现场；Worker/Pod 丢失后从头重跑 CaseRun，
   除非引擎提供并启用经过校验的持久化 checkpoint。
5. 取消=终止进程树；抢占粒度=CaseRun 级。取消与完成竞态由首个成功条件更新裁决；
   终态不可逆，迟到报告只记录审计，不改变结果。
6. 暂停期间是否占用资源配额按 reservation 保留；若 Worker 丢失，先幂等释放旧 attempt
   预留，再决定重试。
7. Executor 的 pause/resume/cancel 对相同 run_id 必须幂等。控制请求先持久化再确认接收；
   Scheduler 重启后重放 pending/processing 请求，外部执行副作用通过幂等 Executor 操作收敛。

## 6. 结果回写与预聚合

- Worker 提交结果事实；Scheduler 在一个事务内校验 attempt 并更新 case_run 状态/结果、
  `last_result_report_id`、case_result 行及
  增量 UPDATE task_summary（对应状态计数）+
  增量 UPDATE task_metric_agg（cnt/pass_cnt/sum_value）。
- `case_result.attempt` 记录结果所属 attempt；`created_at` 是结果事务提交时间，使归档
  保留期从结果产生时开始。重发相同 report_id 时先检查 `last_result_report_id` 并直接返回，
  不再插入结果行或重复更新聚合。
- 只有不再重试的最终 attempt 才能写正式 `case_result` 并更新 `task_metric_agg`；
  retryable timeout/worker_lost 的部分输出不计入聚合。这样每个 CaseRun/metric 只贡献一次，
  p95 也只基于最终有效结果。
- p95 由定时任务基于 case_result 采样或 TDigest 近似，写 task_metric_agg.p95_value。
- 每 30s 对账：COUNT(*) GROUP BY status 校正 task_summary，防增量漂移。
- 查询接口一律读预聚合；下钻走 case_run/case_result 游标分页。

## 7. 幂等与配额

- `request_fingerprint` 命中返回既有 task，除非 dedup=false；dedup 关闭时仍保存指纹，
  但不做唯一冲突复用。指纹覆盖 Set/Scenario 快照校验和、Metric 版本/config、引擎
  digest、规范化 RuntimeConfig 和 seed。
- project_quota：max_running_cases、reserved_high_priority、max_cpu、max_mem_gb。
- 资源槽：worker.capacity（cpu/mem/gpu）与资源预留表为准；worker.used 仅为可重建的
  观测投影。领取与 project/worker 资源预留在同一 DB 事务中锁定并提交，使用
  `(case_run_id, attempt)` 唯一预留键。
- 每个预留在成功、失败、取消、超时或 worker_lost 时释放恰好一次；Scheduler 启动及
  定期对账修复孤儿预留，不能只依赖内存中的 worker.used。
- 高优保留：reserved_high_priority 仅 priority≤2 可用。
- `task_control_request.request_id` 唯一；重复 request_id 返回原请求结果，不重复执行控制动作。
- 每个 task 同时最多一个 pending/processing 控制请求；不同 request_id 的并发控制请求返回
  409，客户端应等待前一请求完成后再提交，避免 pause/resume/cancel 顺序歧义。
- Scheduler 以 `FOR UPDATE SKIP LOCKED` 领取 pending/processing 控制请求；崩溃重启后
  可重放 processing，请求状态与幂等 Executor 操作共同保证收敛。
- 暂停/恢复/取消 API 返回 request_id 与 accepted/rejected 状态；accepted 表示请求已持久化，
  不代表 Executor 动作已完成。最终状态通过 Task 查询/事件读取。

## 8. 安全

- args 模板变量白名单：${SCENARIO_URI} ${OUTPUT_DIR} ${SEED} ${LOG_DIR}。
- env 仅白名单 key 注入；禁止透传宿主环境。
- 每 case 独立输出目录；沙箱 cwd。
- 生产请求必须带已认证主体及 project 授权上下文；API、源数据、日志和 output_uri 读取
  均按 project 校验并写审计记录。开发/CI 可使用显式关闭鉴权的配置。

## 9. 指标（验收）

queued→running P95（高优<1s/常规<5s）；派发吞吐 ≥100 case/s；
暂停<2s；取消<5s；重启恢复<10s；并发领取零重复零丢失；
case 列表 P95<300ms；任务列表 P95<200ms；结果图表 P95<300ms；提交 P95<1s。
性能结果必须附测试画像：数据库与 Worker 规格/数量、并发任务数、CaseRun 时长分布、
冷/热启动比例、测试时长、故障注入比例、数据规模和 P95 统计口径。SQLite 测试不能
替代 PostgreSQL 并发、分区或锁行为验收。

## 10. 引入 MQ/K8s 的判据

- MQ：派发 P95 > 1s 或吞吐 < 100 case/s，且经 Architect 批准。
- K8s：单机资源不足/多机/弹性需求明确。
- 无论是否引入，Executor 接口与 DB 状态机不变。

## 11. 路线（PLAN 参考）

R0 冻结契约 + migrations/001~004
R1 Scenario：文件读写 + 分类/类型/定义/实例 + CRUD + 版本 + 冻结 + Set 分片
R2 Sim：task/case_run 表 + 规模分流提交 + 异步展开 + 幂等 + 游标分页
R3 Scheduler：读取时老化 + 配额 + SKIP LOCKED + LocalExecutor + 心跳/超时/重试
R4 暂停/恢复/取消 + 抢占 + 预聚合回写 + 并发领取单测
R5 结果聚合图表接口 + Playback 起步（DataSource + 按需索引）
R6 万级 cases 压测 + 30 万存量查询压测 + 播放 seek 达标；
   按指标决定是否上 K8sPoolExecutor + MQ。