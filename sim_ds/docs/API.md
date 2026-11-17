# SimCloud API

前缀：`/api`。开发模式可通过 `X-User` / `X-Project` 指定用户与项目；生产模式使用
`Authorization: Bearer <token>` + `X-Project`。错误体统一为：

```json
{ "code": "VERSION_CONFLICT", "message": "场景当前版本已变化，请刷新后重试", "detail": {} }
```

分页统一使用 `cursor` + `page_size`，返回：

```json
{ "items": [], "next_cursor": "base64..." }
```

## 账号与权限

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | 用户名/密码登录，返回 Bearer token 与当前账号 |
| GET | `/auth/me` | 当前账号、角色、最高优先级与资源额度 |
| POST | `/auth/logout` | 注销当前会话 |
| GET | `/users` | 管理员查看账号列表 |
| POST | `/users` | 管理员创建账号并配置优先级/额度 |
| PUT | `/users/{id}` | 管理员修改角色、状态、密码与额度 |

生产环境可使用数据库账号会话；`SIM_API_TOKENS` 静态 token 仍兼容。登录成功后前端使用
`Authorization: Bearer <token>`。

## 场景

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/scenarios?search&tag&tags&tag_mode&tag_expr&status&cursor&page_size` | 场景列表；`tag_expr` 支持 `A&B\|C` 与括号 |
| POST | `/scenarios` | 创建并发布 v1 |
| GET | `/scenarios/{id}?version=` | 读已发布版本文件并校验 checksum |
| PUT | `/scenarios/{id}` | 基于 `version` 创建新版本，冲突返回 409 |
| DELETE | `/scenarios/{id}?hard=` | 归档；硬删检查冻结 Set 引用 |
| GET | `/scenarios/{id}/versions` | 版本历史、发布状态与修改人 |
| POST | `/scenarios/{id}:copy` | 复制最新已发布版本为新场景 |
| GET | `/metrics/templates/{id}/scenarios` | 按 template_id 反查场景 |
| GET | `/tags?search&page_size` | 当前项目已有标签（含使用次数），用于标签下拉框 |

创建示例：

```json
{
  "name": "城市路口-001",
  "source": { "type": "record", "log_id": "src_...", "format": "rsclbag" },
  "time_window": { "start_ts": 0, "end_ts": 180000, "trigger_ts": 60000 },
  "metrics": [{
    "metric_def_id": "safety.brake.hard",
    "metric_def_ver": 1,
    "alias": null,
    "config": {
      "trigger_functions": [{ "template_id": "9", "env": {} }],
      "trigger_ops": ["AND"],
      "functions": [{ "template_id": "30", "env": {} }],
      "ops": [], "ret": "pass", "action": "not_stop_sim",
      "level": "S0", "is_global": false
    }
  }],
  "tags": ["cut-in"]
}
```

## 账号与权限

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | 用户名/密码登录，返回 Bearer token 与当前账号 |
| GET | `/auth/me` | 当前账号、角色、最高优先级与资源额度 |
| POST | `/auth/logout` | 注销当前会话 |
| GET | `/users` | 管理员查看账号列表 |
| POST | `/users` | 管理员创建账号并配置优先级/额度 |
| PUT | `/users/{id}` | 管理员修改角色、状态、密码与额度 |

生产环境可使用数据库账号会话；`SIM_API_TOKENS` 静态 token 仍兼容。登录成功后前端使用
`Authorization: Bearer <token>`。

## 场景集

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/sets?frozen&visibility&cursor&page_size` | 场景集列表；`visibility=public/private` |
| POST | `/sets` | 创建 v1 |
| PUT | `/sets/{id}` | 更新未冻结集合 |
| POST | `/sets/{id}/versions` | 创建新版本（同 PUT）；支持 `visibility` |
| POST | `/sets/{id}:freeze` | 基于当前版本创建冻结 v+1 |
| POST | `/sets/{id}:derive` | 派生新集合 |
| GET | `/sets/{id}` | 当前已发布快照 |
| GET | `/sets/{id}/members?cursor&page_size` | 成员游标分页，返回 `scenario_id/scenario_version/scenario_name` |

冻结成员锁定 `scenario_version`；超过 2000 成员时快照写为
`v{n}.meta.json + v{n}.members.{k}.json` 分片。

## Metric 五层

| 方法 | 路径 |
|---|---|
| GET/POST/PUT/DELETE | `/metrics/categories`、`/metrics/types`、`/metrics/templates`、`/metrics/defs` |
| GET | `/metrics/defs/{id}?version=` |

五层：固定分类 → 类型树 → 模板 `env_schema` → 定义 `(id,version)` → 场景实例 `config`。
Metric ID 由后端按分类自动分配：舒适 1001+ / 合规 2001+ / 安全 3001+ / 效率 4001+ / 导航 5001+。
Scenario.metrics 保存 metric.json 形态的完整对象（id、name、desc 及规则 JSON），不再使用
metric_def_id/metric_def_ver/config/enabled 包装。

Metric 定义可直接携带 `trigger_functions` / `trigger_ops` / `functions` 规则 JSON；
`trigger_templates` / `function_templates` 由其中的 `template_id` 自动派生。
写入场景时执行结构校验 + 模板 JSON Schema 动态校验，错误为 `METRIC_CONFIG_INVALID`
并返回 `detail.path` / `detail.reason`。

## 仿真任务

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/tasks` | 提交任务；>500 cases 返回 202 + `expanding` |
| GET | `/tasks?status&priority&search&mine&cursor&page_size` | 任务列表；`mine=true` 只看当前用户 |
| GET | `/tasks/{id}` | 任务详情 |
| GET | `/tasks/{id}/cases?status&outcome&cursor&page_size` | CaseRun 游标分页，≤500；`outcome=pass/fail` 按指标结果过滤 |
| GET | `/tasks/{id}/cases/{cid}` | Case 下钻（DB 或归档层） |
| GET | `/tasks/{id}/cases/archive?status&cursor&page_size` | Parquet 归档明细 |
| GET | `/tasks/{id}/summary` | 文字结论、通过率、图表数据、失败清单 |
| POST | `/tasks/{id}:pause` / `:resume` / `:cancel` | body `{request_id, reason}`，幂等 |
| GET | `/queue/stats` | 队列深度、状态与优先级分布 |

任务提交示例：

```json
{
  "name": "夜间回归",
  "set_id": "set_...",
  "set_version": 2,
  "runtime": {
    "binary_id": "log-resim",
    "args": ["--scenario", "${SCENARIO_URI}", "--out", "${OUTPUT_DIR}"],
    "env": { "SIM_SEED": "42" },
    "resource": { "cpu": 1, "mem_gb": 1, "gpu": 0 },
    "timeout_sec": 120,
    "retry": { "max": 1, "on": ["timeout", "worker_lost"] }
  },
  "priority": 5,
  "batch": { "max_cases": 0, "shard_size": 1000 },
  "metrics": [],
  "seed": 42
}
```

## 播放

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/sources:extract` | 从 log/manifest 提取数据源 |
| POST | `/sources` | 创建数据源（sim_output 等） |
| GET | `/sources?cursor&page_size` | 数据源列表 |
| POST | `/sources:index` | 异步建索引（202） |
| GET | `/sources/{id}/status` | 索引进度 |
| GET | `/sources/{id}/channels` | 通道索引（仅 ready） |
| GET | `/sources/{id}/chunk?channel&ts&span` | 按时间窗加载样本/帧 |
| GET | `/sources/{id}/frame?channel&ts&idx` | 单帧；video 返回 SVG |

索引写入 `sources/{id}/index.json` 与 `sources/{id}/chunks/{channel}/{n}.json`，文件发布沿用
checksum + 临时对象 + 原子 rename。索引任务在进程重启后由启动恢复逻辑重新入队。

## 系统

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | DB 健康检查 |
| GET | `/stats/overview` | 首屏 KPI：场景数、任务通过率、队列深度 |
| GET | `/stats/users?days=30` | 按用户统计时间范围内任务数、case 数、成功数与指标通过数 |
| GET | `/audit?cursor&page_size` | 项目内审计日志 |
