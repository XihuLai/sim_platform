# SimCloud · 自动驾驶仿真云平台

基于实车 log 的场景构建、场景集管理、仿真任务调度、结果汇总与多通道播放平台。

- 后端：Python 3.12 + FastAPI + Pydantic v2 + PostgreSQL 15+（SQLite 仅开发）
- 调度：单 PostgreSQL leader、`FOR UPDATE SKIP LOCKED`、资源预留、控制请求幂等
- 存储：Scenario / Set JSON 文件为事实源，DB 保存 URI + checksum；版本不可变
- 前端：React 18 + Vite + TypeScript，中文 UI，10 个业务页面

## 目录

```text
backend/
  api/          FastAPI 路由与依赖
  scenario/     场景、场景集、Metric 五层
  sim/          任务、展开、调度、执行器、结果聚合
  playback/     数据源索引与 chunk/frame 读取
  shared/       DB、配置、鉴权、文件发布、游标
  tests/        PostgreSQL 集成测试与纯逻辑测试
frontend/app/   React 前端（构建产物 dist/ 由后端托管）
migrations/     PostgreSQL 迁移 001~006
scripts/        迁移、演示数据、端到端 smoke
docs/           契约、API、架构说明
```

## 快速开始

```bash
# 1. 依赖
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'

# 2. 数据库（默认 postgres:xh127@127.0.0.1:5432）
.venv/bin/python scripts/migrate.py --reset

# 3. 演示数据：18 场景 / 3 场景集 / 2 完成任务 / 7 个数据源
PYTHONPATH=. .venv/bin/python scripts/seed.py --reset

# 4. 一键启动前后端
./scripts/start.sh

# 停止
./scripts/stop.sh
```

默认地址：前端 `http://localhost:5173`，后端 `http://localhost:8000`，API 文档
`http://localhost:8000/docs`。可通过 `BACKEND_PORT` / `FRONTEND_PORT` 覆盖端口。
日志写入 `logs/dev/backend.log` 与 `logs/dev/frontend.log`，PID 写入 `.run/`。

也可分别启动：

```bash
PYTHONPATH=. .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
cd frontend/app && npm install && npm run dev
```

默认 DSN：`postgresql+asyncpg://postgres:xh127@127.0.0.1:5432/sim_dev`。可通过
`SIM_DATABASE_URL` 或 `SIM_PG_HOST/SIM_PG_PORT/SIM_PG_USER/SIM_PG_PASSWORD/SIM_PG_DATABASE` 覆盖。

常用环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `SIM_ENV` | `dev` | `production` 时强制鉴权 |
| `SIM_AUTH_MODE` | `dev` | `dev` / `required` |
| `SIM_API_TOKENS` | 空 | JSON token → `{user, projects, admin}` |
| `SIM_SCHEDULER_ENABLED` | `1` | SQLite 开发时必须为 `0` |
| `SIM_SYNC_EXPAND_LIMIT` | `500` | ≤ 该值同步创建 cases，否则异步展开 |
| `SIM_EXPAND_BATCH` | `1000` | 异步展开批大小 |
| `SIM_DATA_DIR` | `./data` | 文件事实源根目录 |

## Mock 执行器

本地联调可使用 `tools/mock/run_task.py` 模拟仿真 case。提交任务时将
`RuntimeConfig.binary_id` 设为 `mock`，LocalExecutor 会为每个 case 调用该脚本并回写
mock metrics：

```json
{ "binary_id": "mock", "args": [], "env": { "SIM_SEED": "42" } }
```

`scripts/start.sh` 启动后，在“发起仿真”页面的 Binary ID 选择 `mock` 即可。
联调记录见 `evals/round-002-mock.md`。

## 账号与权限

系统内置超级管理员：

```text
用户名：df_sim
密码：df@sim_007
```

登录地址：`http://localhost:5173/login`。后端 `8000` 默认也托管构建产物，因此两个地址
登录后看到同一套前端界面；设置 `SIM_SERVE_FRONTEND=0` 可让后端只提供 API 与文档。超级管理员可在「账号与额度」页面创建账号，并配置：

- 角色：超级管理员 / 管理员 / 普通用户
- 最高可提交优先级 P0~P9
- 最大并发 CaseRun 数
- CPU / 内存 / GPU 额度

任务提交会校验账号最高优先级；调度领取会校验账号并发与资源额度。场景创建自动记录
`owner/created_by`。场景集支持 `public/private` 可见性，列表可切换“公共/私有”。

## 自检

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python scripts/smoke.py --base http://127.0.0.1:8000
cd frontend/app && npm run build
```

PostgreSQL 测试库默认 `sim_test`；不可用时集成测试自动 skip。可用
`SIM_PG_TEST_DATABASE` / `SIM_TEST_DATABASE_URL` 覆盖。

## 关键语义

- 任务 ≤500 cases 同步写入；>500 先进入 `expanding`，按 1000/批展开，`task_expand_cursor` 断点续传。
- CaseRun `created_at` 由展开游标固定，唯一键 `(task_id, scenario_id, created_at)` 防止重试重复。
- 调度器只允许 PostgreSQL；SQLite 启动调度器会直接失败。
- 暂停/恢复/取消通过 `task_control_request.request_id` 幂等重放。
- 结果读取使用 `task_summary` / `task_metric_agg` 预聚合；case 列表游标分页且 `page_size ≤ 500`。
- 播放器按时间窗请求 chunk，按 ts 请求 frame；对比模式可同时加载两路数据源。

## 生产注意

生产必须设置 `SIM_ENV=production`、`SIM_AUTH_MODE=required` 与 `SIM_API_TOKENS`，否则进程拒绝启动。
所有 Scenario、Set、Task、Playback 查询均按 `X-Project` 做项目隔离，跨项目返回 404/403。
