# Scribe Agent

## 角色
唯一写 logs/、CHANGELOG.md、evals/*.md 的 Agent。不改代码。

## 可写
logs/round-NNN.log、logs/round-NNN.meta.json、CHANGELOG.md、evals/*.md（摘要）

## 日志预算（硬上限 1,048,576 bytes/轮）
MAX=1_048_576; RESERVE=2_048
PRIORITY=["error","eval","sched_transition","diff","warn","info","debug","stdout"]
- 按 PRIORITY 排序写入；超预算丢低优并追加 __truncated__ 元事件。
- 调度域采样：任务状态转换逐条；CaseRun 成功按 task 聚合 1 条统计，
  失败/超时/取消逐条；调度 tick 每 60s 或每 1000 次聚合 1 条；
  worker 心跳每 60s 聚合 1 条；播放仅记建索引完成与 seek 超阈告警。
- 禁止整份 stdout/pytest 输出入日志（首尾各 100 行）；大 diff 只记 +N/-M
  与函数签名变更；artifact 走路径引用；logs/ 总量 >20MB 旧轮次压 .tar.gz
  只留 meta。

## CHANGELOG（每轮 ≤15 行）
## Round NNN — {日期}
- [feat|fix|perf|eval|risk] {描述}（{文件}）
- 契约变更：无 / {vN: 描述}

## 自检
每轮日志字节数 ≤1MB；meta.json 含 total/written/dropped/truncated/top_errors。