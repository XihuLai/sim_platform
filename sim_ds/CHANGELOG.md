# CHANGELOG

## Round 001 — 实现轮 — 2026-11-12
- [feat] Scenario/Set 不可变版本发布、checksum 校验、pending 崩溃恢复与并发 expected_version 冲突
- [feat] Metric 五层 CRUD、模板 env_schema 动态校验、required 模板检查
- [feat] 任务 ≤500 同步 / >500 异步展开、固定 case_run_created_at、断点幂等、分批重算预聚合
- [feat] PostgreSQL 单 leader 调度：SKIP LOCKED、aging、project/worker 资源预留、outbox、暂停/恢复/取消幂等
- [feat] 心跳/超时/worker_lost 检测、重试、资源恰好释放一次、task_summary/task_metric_agg 增量与对账
- [feat] 播放数据源异步索引、chunk/frame 按需读取、单/对比多通道播放器
- [feat] React 10 页中文 UI、游标分页、虚拟列表、状态图/指标柱状图、失败下钻、播放入口
- [test] 29 个 PostgreSQL 集成/纯逻辑测试；501 cases 异步展开；smoke 覆盖场景→集→任务→结果与播放 seek
- [migration] 新增 006_set_version_created_at.sql（恢复排序键）
- [docs] 新增 README、docs/API.md、docs/ARCHITECTURE.md、CI workflow

## Round 001 — 2026-11-11
- [breaking] 四份契约升级至 v2.0：所有 >500 cases 任务异步展开；Scheduler 状态转换入口唯一；
  明确暂停在 Worker/Pod 丢失后的重跑语义、生产 project 隔离和复现指纹；
  Set 容量提高到 10000 以覆盖单任务万级 cases，freeze 创建新的不可变版本
- [design] 技术栈/存储/调度契约：文件版本不可变发布与修复、
  PostgreSQL CI 集成测试、分区归档查询、资源预留及性能负载画像
- [migration] 新增 migrations/004_scheduler_integrity.sql：request fingerprint、
  dedup 控制、版本发布状态、展开唯一索引、结果 attempt/report ID、资源预留和持久化任务控制请求表，
  并创建当前月及未来 3 个月分区；
  不改写 migrations/001~003
- [plan] 增加 Round 1 的展开/调度、资源预留、文件恢复、项目隔离和归档验收任务
- [rollback] 迁移 004 回滚前必须解决重复 legacy task key，再恢复旧唯一约束；参见 migration 注释
- 契约变更：v2.0（BREAKING）

## Round 000 — 初始冻结
- [feat] 冻结 4 份契约（总/技术栈/存储/调度）与 7 个 Agent Prompt
- [feat] migrations/001~003（基础表 / Metric 五层 / 分区+预聚合+展开游标）
- [risk] mcap 解析与播放器索引为桩，待后续轮次替换
- 契约变更：v1.1 初始冻结（含万级 cases/30万存量规模适配）