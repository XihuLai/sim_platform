# Round 001 验收记录

日期：2026-11-12（Asia/Shanghai）
范围：场景/场景集/Metric、仿真任务展开调度、播放器、前端 10 页、文档与 smoke。

## 1. 自动化测试

命令：

```bash
PYTHONPATH=. .venv/bin/python -m pytest --disable-warnings -q
```

结果：`29 passed`（PostgreSQL `sim_test`，无 skip）。

覆盖重点：

- 任务状态纯函数、重试规则。
- 游标编解码、canonical JSON、FileStore 原子发布/临时对象恢复/路径越界。
- Metric 结构校验与 template env_schema 动态校验。
- Scenario 版本发布、过期版本冲突、文件缺失标记 `unavailable`。
- Set 冻结、派生、冻结后不可更新、成员游标分页。
- 同步任务 1 case 实际执行、结果聚合、dedup、跨项目读取拒绝。
- **501 cases**：>500 自动 `expanding`，一次展开 501 条，重复执行不产生重复 CaseRun，游标停在 501。
- 播放数据源异步式建索引、channels/chunk/frame、seek 耗时断言 < 500ms。
- 生产鉴权启动校验、API health/catalog smoke。

## 2. 万级展开与游标分页

在独立 PostgreSQL `sim_test` 中直接构造 10,000 个 Scenario 与冻结 Set：

```text
cases               10000
distinct_scenarios  10000
cursor_offset       10000
task status         queued
task total_cases    10000
page1 / page2       500 / 500
elapsed             11.11s
```

任务使用 `SIM_EXPAND_BATCH=1000`，断点游标推进到 10000；CaseRun 唯一约束验证无重复。
case 接口 `page_size=500` 两页无重叠，符合契约上限。

## 3. 端到端 smoke

命令：

```bash
PYTHONPATH=. .venv/bin/python scripts/smoke.py --base http://127.0.0.1:8099
```

关键输出：

```json
{
  "health": {"ok": true, "body": {"status": "ok", "database": "postgresql"}},
  "scenario_page": {"ok": true},
  "scenario_no_overlap": {"ok": true},
  "task_list": {"ok": true},
  "summary": {"ok": true},
  "summary_text": "任务「异步展开压测任务」共 520 个用例，执行成功 520 个，指标通过 423 个，通过率 81.35%。",
  "case_no_overlap": {"ok": true},
  "source_ready": {"ok": true},
  "playback": {"ok": true},
  "playback_seek_ms": 6.5,
  "playback_under_500ms": {"ok": true}
}
```

场景→集→任务→结果链路另由 seed（真实 Service + Scheduler + LocalExecutor 子进程）与
`test_task_sync` / `test_scenario_set` 覆盖；Playback seek 实测 6.5ms。

## 4. 前端

```bash
cd frontend/app
npm run build
```

结果：TypeScript 编译 + Vite 构建成功。

```text
dist/index.html                 0.42 kB
dist/assets/index-*.css        13.39 kB
dist/assets/index-*.js        216.33 kB (gzip 68.90 kB)
```

后端 `/`、`/scenarios`、`/tasks`、`/playback` SPA 路由均返回 200。

## 5. 代码约束

- 后端/脚本：所有 Python 文件 ≤ 400 行，所有函数 ≤ 50 行。
- 前端：所有页面/组件 ≤ 200 行。
- `python -m compileall backend scripts` 通过；自定义 AST 检查无未使用 import、无超长函数/文件。
- 无 TODO/FIXME 遗留；无调试 print（仅 CLI/seed 的正式输出）。

## 6. 静态检查与限制

- `ruff check backend scripts`：All checks passed。
- `mypy backend`：Success: no issues found in 43 source files（strict，测试目录排除）。
- `python -m compileall backend scripts` 通过。
- 归档导出仅实现查询与 Parquet 读取路径（缺 pyarrow 时 503）；分区 DETACH/导出作业与
  30 万存量压测未在本地执行，Round 1 T5 保持未勾选。
- K8s Executor、真实 mcap/bag 解析仍为后续生产替换点（见 docs/ARCHITECTURE.md 已知取舍）。
