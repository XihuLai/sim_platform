# Sim-Scheduler Agent

## 角色
仿真域后端：提交、展开、调度、执行、暂停/取消/恢复、预聚合、评测。

## 只读
docs/CONTRACT*.md、docs/PLAN.md

## 可写
backend/sim/**、migrations/（经 Architect 评审）、backend/tests/sim/**

## 必做
A. 提交与展开
   - 按规模分流：≤500 同步展开；500~5000 异步展开；>5000 写 expanding +
     异步分片展开（每批 1000，COPY/executemany）。
   - task_expand_cursor 断点续传；展开完成置 queued；失败置 failed 记原因。
   - 幂等：UNIQUE(set_id,set_version,runtime_hash,metrics)。
B. 调度
   - 领取：FOR UPDATE SKIP LOCKED，ORDER BY 内计算老化优先级（不物化全表），
     小批量高频（20~100/tick），短事务。
   - 心跳超时回收（仅 timeout/worker_lost，attempt<retry.max）。
   - 抢占：限定同 project / running 集合选最低优 victim，Executor.pause（非 kill）。
   - 配额：project_quota + reserved_high_priority（priority≤2）。
C. 执行（Executor）
   - 实现 Executor Protocol；LocalExecutor 起步（SIGSTOP/SIGTERM→SIGKILL）。
   - args 模板白名单（SCENARIO_URI/OUTPUT_DIR/SEED/LOG_DIR）；env 白名单。
   - 每 case 独立输出目录；沙箱 cwd；超时置 timeout 并按 retry 重试；
     用户 cancel 不重试。
D. 结果与预聚合
   - 回写 case_run 状态/结果 + case_result 行 + 增量更新 task_summary /
     task_metric_agg；p95 定时计算或 TDigest；每 30s 对账。
   - summary 接口读预聚合；case 列表/失败清单游标分页（page_size≤500）。
E. 分区
   - 确保 case_run/case_result 写当月分区；迁移建 3 个月分区 + 定时建下月；
     提供 DETACH 归档脚本骨架（Parquet 导出）。

## 禁止
- 阻塞 API；一次性构造万级 Pydantic 返回；全量 COUNT 扫 case_run。
- 每 tick 全表 UPDATE effective_priority。
- OFFSET 深翻 case 列表。
- 先查后改领取（必须 SKIP LOCKED）。

## 自检
lint + mypy + pytest：优先级/老化/抢占/暂停恢复/取消/超时重试/幂等/配额/
并发领取零重复/异步展开断点/预聚合增量与对账/游标分页/分区写入。