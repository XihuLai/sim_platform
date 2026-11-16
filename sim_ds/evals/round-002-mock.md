# Mock 执行器联调与回归测试记录

日期：2026-11-12
对象：`tools/mock/run_task.py` + 当前前后端版本
目标：用 mock 任务真实走通提交、调度、执行、结果聚合、失败下钻和播放入口。

## 1. 测试方式

- 后端：PostgreSQL `sim_dev`，本地 `uvicorn` `8000`。
- 前端：Vite `5173`，通过 `/api` 代理访问后端。
- 任务执行：`RuntimeConfig.binary_id = "mock"`，LocalExecutor 调用
  `tools/mock/run_task.py`，每个 case 使用稳定派生 seed。
- 浏览器：真实 Chromium 操作页面，检查 DOM、请求和 console error。

mock 命令示例：

```bash
python tools/mock/run_task.py --job-id tsk_xxx --task-id run_xxx --seed 12345
```

## 2. 覆盖场景

| 场景 | 结果 |
|---|---|
| mock 单 case CLI 输出 | 通过 |
| API 提交 6 cases mock 任务 | 6 个 case 执行完成，mock 指标入库 |
| 前端“发起仿真”选择 mock 并提交 | 通过，任务进入调度并完成 |
| 任务详情轮询 | 完成后 header 与 CaseRun 列表同步刷新 |
| 结果汇总 | 状态环形图、Metric 柱状图、失败清单正常 |
| 指标未通过下钻 | `outcome=fail` 返回 5 条，页面显示“指标未通过” |
| mock 崩溃 case | 通过 seed 探测得到 `worker_lost` 失败，原因已入库 |
| 失败 → 播放入口 | 跳转 `/playback?case=...`，播放器加载并渲染 SVG |
| 场景创建手动数据源 | Log ID / URI / checksum / format 可填写，创建成功 |
| 创建后 KPI | 场景数立即刷新；队列深度周期刷新 |
| 场景集创建/冻结 | 2 成员场景集创建成功，冻结后变为 v2 已冻结 |
| 任务列表 | 终态任务不再显示暂停/取消 |
| 队列看板 | 状态标签中文化，图表正常 |
| Metric 页面 | 五层树、模板 schema、定义详情正常 |

## 3. 发现并修复的问题

| # | 问题 | 根因 | 修复 | 验证 |
|---|---|---|---|---|
| 1 | `binary_id=mock` 仍执行内置 `engine_cli` | LocalExecutor 未分支 mock 命令 | 增加 mock 命令构造与稳定派生 seed | 6-case mock 任务指标来自 mock pool |
| 2 | mock 失败/指标未通过原因丢失 | 执行器失败时只读 stderr；mock 原因在 stdout JSON | 优先从 mock report 的 `reason` 回写 | 失败 case reason=`worker_lost`；指标失败 reason=`metric_threshold_exceeded` |
| 3 | 结果汇总失败清单漏掉“执行成功但指标失败”的 case | 只按 `case_run.status` 过滤 | 新增 `outcome=fail/pass`；汇总与 case 列表统一按 `case_result.pass` 判定 | 6 cases 中 5 个指标失败，失败清单 5 条 |
| 4 | 任务完成后 CaseRun 列表仍显示“排队中” | 详情页只轮询 task，不刷新 cases | 活跃期同时刷新 cases；任务状态变化时强制刷新 | 页面自动从 6 个排队变为成功/指标未通过 |
| 5 | 任务完成后顶部队列深度仍为旧值 | KPI 只在路由变化时刷新 | Layout 每 5 秒刷新 overview | 任务完成后 queue_depth 自动回到 0 |
| 6 | 已结束任务仍显示“暂停/取消” | 列表未按终态隐藏控制 | 终态仅显示“结果”；expanding 不显示暂停 | 成功任务行仅保留“结果” |
| 7 | 未冻结场景集显示“排队中” | 复用任务状态 `queued` | 新增 `draft/frozen` 状态与样式 | 场景集显示“未冻结/已冻结” |
| 8 | 场景创建无法填写完整数据源 | 只有 Log ID，URI/checksum/format 不可编辑 | 新增 SourceEditor，支持选择已有源自动填充和手动编辑 | 浏览器创建成功，JSON 保存手动 URI |
| 9 | 创建场景后跳转 `/scenarios/undefined/edit` | 后端 detail 返回 `scenario_id`，前端取 `id` | 后端响应补 `id`，前端兼容 `id/scenario_id` | 正确跳转并显示版本历史 |
| 10 | 创建场景后总场景数不更新 | KPI 只随项目变化刷新 | KPI 依赖路由变化并周期刷新 | 创建后场景数 18→20 即时更新 |
| 11 | 队列看板状态为英文 | 直接使用 status key | 增加中文 `statusLabel` | 显示“失败/成功” |

## 4. 自动化回归

新增 `backend/tests/test_mock_executor.py`：

- 提交 `binary_id=mock` 任务并真实执行 mock 子进程；
- 校验成功 case 的 metrics 来自 mock metric pool；
- 校验 `summary.failures` 数量与 `fail_count` 一致；
- 校验 `GET /tasks/{id}/cases?outcome=fail` 与失败数一致。

最终检查：

```text
ruff check backend scripts      All checks passed
mypy backend                     Success: no issues found in 43 source files
pytest                          30 passed
frontend npm run build          success
```

## 5. 剩余非阻塞限制

- mock 输出目录没有真实视频/点云 artifact，播放器打开 case 后仍默认选择已有 DataSource，未按 case 自动创建播放源。
- Metric 管理页面当前只读，无新建/编辑表单。
- 场景集创建页已支持按场景 ID/标签筛选和成员版本选择；详见 Round 003 变更。
- 分区归档、K8s Executor、真实 mcap/bag 引擎仍不在本轮 mock 测试范围内。
