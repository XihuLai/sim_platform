# PLAN

> Architect 每轮维护。格式：
> ## Round N — {日期}
> - [ ] T{n} {任务} | 归属: {agent} | 验收: {可测标准}
> 契约变更：无 / {vN: 描述}

## Round 0 — 2026-11-11
- [x] T1 更新并对齐 4 份契约 + migrations/001~004 | 归属: architect | 验收: 展开、状态转换、控制请求、文件发布、资源预留及归档规则在文档和迁移中一致；规模: 万级/30万级
- [x] T2 目录骨架 + CI（ruff/mypy/pytest） | 归属: architect | 验收: SQLite 便携测试与 PostgreSQL 集成 CI 通过；可观测: CI 结果可追溯
契约变更：v2.0（总/技术栈/存储/调度；BREAKING，详见 CHANGELOG）；新增 migration 004，旧迁移不改写

## Round 1 — 2026-11-11
- [x] T1 实现展开门槛、控制请求与状态转换入口 | 归属: sim-scheduler | 验收: PostgreSQL 集成测试覆盖 500/501 cases、断点重试无重复、调度器重启后控制请求幂等恢复、过期 attempt 和取消竞态不覆盖终态；规模: 万级 cases
- [x] T2 实现资源预留与释放 | 归属: sim-scheduler | 验收: 并发领取压测不超 project/worker CPU、内存、GPU 配额；失败/取消/失联各释放恰好一次；规模: 30万存量
- [x] T3 实现不可变文件发布与巡检恢复 | 归属: scenario | 验收: 注入发布前后进程故障、DB 提交失败、并发版本冲突和 Set freeze 版本创建；无损坏文件被当作有效快照，无孤儿文件静默成为当前版本；规模: 1万成员 Set
- [x] T4 协调并验证生产身份与 project 隔离 | 归属: architect | 验收: 跨 project 访问 Scenario、Set、任务、日志、artifact、Playback source 均拒绝；未认证生产配置启动失败；可观测: 审计可查询
- [ ] T5 验证分区归档与性能目标 | 归属: evaluator | 验收: PostgreSQL 覆盖分区创建/归档重试/Parquet 校验/历史下钻，并验证 active/近期完成 CaseRun 阻止过早 detach；附数据库与 Worker 规格、并发任务、CaseRun 时长分布及 P95 口径；规模: 30万存量
契约变更：无；实现验收按 v2.0 契约