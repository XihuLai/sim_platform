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
migrations/     PostgreSQL schema migrations
scripts/        迁移、演示数据、端到端 smoke
docs/           契约、API、架构说明
```

## 快速开始

```bash
# 1. 依赖
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

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
# 后端静态检查、类型检查、测试
.venv/bin/ruff check backend scripts
.venv/bin/mypy backend
PYTHONPATH=. .venv/bin/python -m pytest -q

# 前端类型检查与生产构建
cd frontend/app
npm ci
npm run build
```

PostgreSQL 测试库默认 `sim_test`；不可用时集成测试自动 skip。可用
`SIM_PG_TEST_DATABASE` / `SIM_TEST_DATABASE_URL` 覆盖。

端到端 smoke（需先启动 Backend，并准备可登录的测试账号/测试数据）：

```bash
PYTHONPATH=. .venv/bin/python scripts/smoke.py --base http://127.0.0.1:8000
```

## 构建、打包与部署

### 本地开发环境

```bash
# 建立 Python 环境并安装应用和开发/K8s 测试依赖
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

# 安装前端依赖；package-lock.json 存在时使用 npm ci 保持依赖版本一致
cd frontend/app
npm ci
cd ../..

# 编译检查 Python 源码
.venv/bin/python -m compileall -q backend scripts

# 初始化本地开发数据库（会清空 public schema；只可对开发库执行）
SIM_ENV=dev .venv/bin/python scripts/migrate.py --reset

# 启动 Backend + Vite 前端；停止使用 ./scripts/stop.sh
./scripts/start.sh
```

默认由本地 PostgreSQL 提供 `sim_dev` 数据库。使用其他数据库时，先设置
`SIM_DATABASE_URL` 或 `SIM_PG_HOST/SIM_PG_PORT/SIM_PG_USER/SIM_PG_PASSWORD/SIM_PG_DATABASE`。
`--reset` 会删除并重建目标库的 `public` schema，禁止对测试或生产数据执行。

### 构建前端与 Python 包

```bash
# 前端 TypeScript 检查并构建静态资源；Backend 默认从 data_dir 对应的 frontend/app/dist 托管
cd frontend/app
npm ci
npm run build
cd ../..

# 构建后端 wheel/sdist 到 dist/
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

Python 包仅包含 `backend` 与 `scripts`。仓库没有 Backend 应用 Dockerfile；Backend 镜像、
Service/Ingress 和 Secret 挂载由部署平台自己的镜像/清单管理。Worker 镜像独立构建如下。

### 构建并发布 K8s Worker 镜像

需要 Docker/BuildKit 和有 push 权限的镜像仓库。将仓库地址和版本标签替换为实际值：

```bash
export WORKER_IMAGE=registry.example.com/sim/sim-worker:2026-11-18
docker build -f Dockerfile.worker -t "$WORKER_IMAGE" .
docker push "$WORKER_IMAGE"
```

Worker 镜像基于 `Dockerfile.worker`，使用非 root 用户，不包含数据库驱动、Kubernetes
客户端或 PVC。K8s 中由 Backend/Scheduler 自动创建或更新 Worker Deployment，不需要单独
`kubectl apply` Worker YAML。

### 测试与生产环境部署

测试和生产必须部署独立 Backend/Scheduler、PostgreSQL、K8s namespace/Worker Pool、Worker
Secret/Token 及对象存储 bucket/prefix。**不能共用调度数据库或 outbox**：不同环境的 Pool
否则可能领取并执行对方任务。默认 `SIM_ENV=test` 与 `SIM_ENV=production` 会分别使用
`sim_test`/`sim_prod` 数据库名、`sim-test`/`sim-production` namespace、
`sim-worker-test`/`sim-worker-production` Pool，以及 `sim/test`/`sim/production` 对象存储
prefix；如果指定环境变量覆盖这些值，仍须确保实际资源互相隔离。每个 Pod 默认一个 slot，
整个 Pool 并发数为 `SIM_K8S_POOL_REPLICAS × SIM_K8S_WORKER_SLOTS`。

Backend/Scheduler 的非敏感运行与 Pool 配置可放在 YAML 中，格式为一组 `SIM_*` 键值；
通过 Backend 容器的 `SIM_CONFIG_FILE` 指定文件。环境变量优先于 YAML，可从 Kubernetes Secret
注入敏感变量并覆盖相应配置。配置示例见 [k8s-test.yaml.example](config/k8s-test.yaml.example)。
加载器拒绝 YAML 中的数据库 DSN/密码、API token、Worker token 和 S3 密钥。任务级
`RuntimeConfig`（如 Binary URI、args、env、timeout、资源请求）仍随任务提交，由 Scheduler
claim API 传给 Worker；这些动态参数不属于静态 Pool YAML。

示例：部署测试环境。生产使用同一流程，将 `test` 替换为 `production`，并换成生产数据库、
镜像、Scheduler URL、namespace、Secret 和对象存储凭据。

```bash
export ENV_NAME=test
export K8S_NAMESPACE=sim-test
export WORKER_IMAGE=registry.example.com/sim/sim-worker:2026-11-18
export BACKEND_DEPLOYMENT=sim-backend-test

# 建 namespace，并为测试 Worker 建立独立 Secret env 文件。
kubectl create namespace "$K8S_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
# /secure/path/sim-worker-test.env 需包含 SIM_WORKER_TOKEN 和 S3 凭据；
# 文件应由 Secret 管理流程生成，不要提交到代码库。
kubectl create secret generic sim-worker-secrets \
  --namespace "$K8S_NAMESPACE" \
  --from-env-file=/secure/path/sim-worker-test.env \
  --dry-run=client -o yaml | kubectl apply -f -

# 创建 Backend/Scheduler 使用的非敏感 ConfigMap。
kubectl create configmap sim-backend-config \
  --namespace "$K8S_NAMESPACE" \
  --from-file=sim-test.yaml=config/k8s-test.yaml.example \
  --dry-run=client -o yaml | kubectl apply -f -
```

Backend Deployment 需由部署平台预先创建。将以下内容合并到 Backend 容器的 Deployment
模板（容器名需匹配现有部署），挂载 ConfigMap 并设置配置文件路径。`sim-backend-secrets`
应包含 Backend 所需敏感环境变量，如 `SIM_DATABASE_URL`、`SIM_API_TOKENS`、
`SIM_WORKER_TOKEN` 和 S3 凭据。

```yaml
spec:
  template:
    spec:
      containers:
        - name: backend
          env:
            - name: SIM_CONFIG_FILE
              value: /etc/sim/sim-test.yaml
          envFrom:
            - secretRef:
                name: sim-backend-secrets
          volumeMounts:
            - name: sim-backend-config
              mountPath: /etc/sim
              readOnly: true
      volumes:
        - name: sim-backend-config
          configMap:
            name: sim-backend-config
```

ConfigMap 示例文件可按环境复制、修改非敏感参数后创建；`sim-worker-secrets` 应提供 Worker
所需的同一个 `SIM_WORKER_TOKEN` 和 S3 凭据。Secret 环境变量优先于 YAML，禁止将密钥放进
ConfigMap。Worker Pod 由 Backend 自动创建，不需要单独 `kubectl apply`。

```bash
# SIM_TEST_DATABASE_URL 由受控环境提供，必须指向独立测试库；不要留空。
: "${SIM_TEST_DATABASE_URL:?Set SIM_TEST_DATABASE_URL to the isolated test database}"
# 先对明确指定的测试库应用增量迁移（不要带 --reset）。
SIM_DATABASE_URL="$SIM_TEST_DATABASE_URL" .venv/bin/python scripts/migrate.py

# Backend 启动后会创建/更新 Worker Deployment。等待 Backend 和 Worker 均就绪。
kubectl rollout status "deployment/$BACKEND_DEPLOYMENT" --namespace "$K8S_NAMESPACE"
kubectl rollout status deployment/sim-worker-test --namespace "$K8S_NAMESPACE"
kubectl get deployments,pods --namespace "$K8S_NAMESPACE"
```

`SIM_TEST_DATABASE_URL` 应由受控环境提供并指向独立测试 PostgreSQL。Backend Deployment
应有权限读取 ConfigMap 挂载文件。Scheduler 的 ServiceAccount 需有该 namespace 内
Deployment 的 get/create/patch 权限；Worker 不需要 Kubernetes API 权限。
`SIM_WORKER_API_URL` 必须从 Worker Pod 网络可达。

检查部署和日志：

```bash
kubectl get deployments,pods --namespace "$K8S_NAMESPACE"
kubectl logs deployment/sim-worker-test --namespace "$K8S_NAMESPACE" --all-containers=true
kubectl logs "deployment/$BACKEND_DEPLOYMENT" --namespace "$K8S_NAMESPACE" --all-containers=true
```

注意：Backend 在启动时读取 `SIM_CONFIG_FILE`。修改 ConfigMap 后需重启 Backend Deployment
使新配置生效；如果部署平台以 Helm/GitOps 管理 Deployment，应把 ConfigMap volume、mount 和
环境变量更新到对应 values/配置源。本仓库不提供 Backend Deployment YAML、Helm chart 或
Ingress 配置。

### 正式环境上线步骤清单

1. **确认发布版本**：固定 Backend 与 Worker 镜像 tag/digest；完成审查、依赖检查及 CI，
   不使用 `latest`。
2. **准备隔离资源**：为正式环境独立创建 PostgreSQL 数据库、K8s namespace、Worker Pool、
   对象存储 bucket/prefix 和 Scheduler 域名；不复用测试数据库、outbox、Token 或存储凭据。
3. **准备权限和密钥**：配置 Scheduler 最小 RBAC（目标 namespace 中 Worker Deployment 的
   get/create/patch）；创建 Backend/Worker Secrets，确认两侧 Worker Token 一致，并验证镜像仓库、
   PostgreSQL、对象存储权限。
4. **准备 YAML**：以 `config/k8s-test.yaml.example` 为模板生成正式 ConfigMap，设置
   `SIM_ENV=production`、正式镜像、namespace、Pool、副本数、`WORKER_SLOTS=1`、Scheduler URL
   和对象存储 bucket/prefix；核验配置不含敏感值且网络地址可达。
5. **备份并迁移**：备份正式数据库；确认迁移目标是正式库后运行 `scripts/migrate.py`
   （不带 `--reset`）；确认集群配额满足 Pool 的 replicas × slot 资源请求。
6. **部署并观察**：更新 Backend Deployment 的 ConfigMap 挂载和 `SIM_CONFIG_FILE`，发布
   固定版本 Backend；等待 Backend rollout 后检查它创建/更新的 Worker Deployment 和 Pod。
   查看应用日志、RBAC 拒绝、镜像拉取及 Scheduler/S3 连通性。
7. **Canary 验收**：提交小型正式任务，确认 Worker 领取正确 attempt、输入 checksum 校验通过、
   输出上传成功、报告落库且结果/指标正确；验证 pause/resume/cancel 与失败重试。
8. **放量与回滚**：canary 通过后逐步增加 Pool replicas；保留上一版镜像和 ConfigMap。
   应用回滚只恢复兼容的镜像/配置，数据库变更按已审查的向后兼容策略回滚或前滚；
   不对生产库执行 `--reset`。

### CI 中的验证命令

`.github/workflows/ci.yml` 的 CI 使用 PostgreSQL 16，并运行以下命令；本地集成测试也建议
提供 PostgreSQL，而非仅依赖 SQLite：

```bash
.venv/bin/ruff check backend scripts
.venv/bin/mypy backend
PYTHONPATH=. .venv/bin/python -m pytest -q
cd frontend/app && npm install --no-audit --no-fund && npm run build
```

## 关键语义

- 任务 ≤500 cases 同步写入；>500 先进入 `expanding`，按 1000/批展开，`task_expand_cursor` 断点续传。
- CaseRun `created_at` 由展开游标固定，唯一键 `(task_id, scenario_id, created_at)` 防止重试重复。
- 调度器只允许 PostgreSQL；SQLite 启动调度器会直接失败。
- 暂停/恢复/取消通过 `task_control_request.request_id` 幂等重放。
- 结果读取使用 `task_summary` / `task_metric_agg` 预聚合；case 列表游标分页且 `page_size ≤ 500`。
- 播放器按时间窗请求 chunk，按 ts 请求 frame；对比模式可同时加载两路数据源。

## 生产注意

生产必须设置 `SIM_ENV=production` 和 `SIM_AUTH_MODE=required`，并启用数据库账号鉴权或配置
`SIM_API_TOKENS`，否则进程拒绝启动。
所有 Scenario、Set、Task、Playback 查询均按 `X-Project` 做项目隔离，跨项目返回 404/403。
