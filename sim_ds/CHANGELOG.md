# CHANGELOG

## Round 031 — K8s 执行器与 OSS Worker 基线 — 2026-11-17
- [contract] 确认 Worker 通过 S3-compatible SDK 直读场景/Binary、上传结果；不挂载 PVC、不直连 DB；结果回调 Scheduler 落库
- [feat] 增加可插拔 Executor 协议与 K8sPoolExecutor（Deployment + HTTP outbox claim）；默认每 Pod 一个 slot
- [feat] 增加 Worker claim/start/heartbeat/result API、S3 FileStore 和 Worker 进程；Binary 使用 s3:// URI 与强制 SHA-256
- [deploy] 新增可选依赖 kubernetes Python client 与 boto3；LocalExecutor 默认不需要初始化 K8s
- [deploy] 测试与生产必须使用独立 Scheduler 部署和 PostgreSQL 数据库，Worker Pool/namespace/密钥/对象存储分别隔离
- [pending] 目标集群部署/联调待提供 namespace、镜像仓库、Scheduler URL、RBAC、对象存储 endpoint/bucket 与网络策略

## Round 030 — Web 发起 3 cases 全流程验收 — 2026-11-17
- [test] norm_sim 通过前端创建/冻结 3 成员场景集「前端3Case测试集」v2，并从「发起仿真」提交 mock_case 任务
- [test] Executor 对 3 个 case 分别调用 test_mock_run_case.py，任务 tsk_20261117130320e1db9d：3/3 执行成功、3/3 指标通过
- [fix] Executor 日志目录改为 data/logs/{task_id}/{case_run_id}/，避免并发 case 互相覆盖 run.log
- [fix] test_mock_run_case.py 在 function_field_name 未命中时按 metric 名称回退规则，避免误报 unknown_function
- [test] 结果汇总通过率 100%，Case 下钻显示 0.049/pass，播放器画面与通道正常且无 console error

## Round 029 — Web 全流程测试与播放器修复 — 2026-11-17
- [test] 普通用户 norm_sim 通过前端完成：登录 → 选择冻结集合 → mock 发起任务 → 进度 → 结果汇总 → 失败清单 → 播放器
- [fix] 播放器未选择数据源时不再请求 /api/sources//channels，消除 404 console error
- [test] test_mock_run_case.py 兼容新版 Scenario.metrics，单 case 实测 pass

## Round 028 — 复制场景延迟创建 — 2026-11-17
- [feat] 点击「复制」改为进入预填的复制场景页，不立即创建
- [feat] 复制页预填源场景名称/数据源/时间窗/标签/Metric/extra，保存后才创建新场景
- [feat] 复制页新增「取消」，取消只返回列表，不产生场景
- [test] 浏览器实测：复制后取消场景数不变；复制后保存场景数 +1

## Round 027 — 场景编辑取消修复 — 2026-11-17
- [fix] 移除重复的「放弃更改」按钮，只保留「取消并返回列表」
- [fix] 取消按钮显式 type=button 且只执行路由返回，不触发保存/复制
- [test] 浏览器点击取消后场景总数保持不变（25→25）

## Round 026 — 管理员删除场景 — 2026-11-17
- [feat] 场景列表为管理员/超级管理员显示「删除」，执行永久删除
- [security] 普通用户硬删除返回 403，仍只能归档
- [security] 被任何场景集版本引用的场景禁止硬删除（409 SCENARIO_REFERENCED）
- [test] 增加管理员删除、普通用户拒绝、引用保护测试

## Round 025 — 场景编辑取消/放弃更改 — 2026-11-17
- [feat] 场景编辑页新增「放弃更改」，恢复为服务端当前版本数据
- [feat] 顶部新增「取消并返回列表」，有未保存修改时二次确认
- [feat] 编辑中显示“有未保存的修改”提示
- [test] 浏览器实测修改名称后可放弃恢复为原值

## Round 024 — 场景/统计/额度/输出路径 — 2026-11-17
- [feat] 场景支持复制新场景；场景列表支持归档；归档场景不出现在新建场景集选择中
- [feat] Scenario 版本历史显示修改人 created_by
- [feat] 发起仿真移除 Metric keys/Args/CPU/内存/GPU；资源使用默认值
- [feat] 默认输出目录改为 /tmp/{task_id}/{case_run_id}；支持 RuntimeConfig.env.OUTPUT_DIR 覆盖
- [feat] 新增数据统计页 /stats：按时间范围统计用户任务数与 case 累计
- [feat] 账号额度新增每日 case 上限并在任务提交时校验；CPU/内存/GPU 额度 UI 隐藏且不参与调度
- [feat] 任务列表默认“只看我的任务”，管理员可取消筛选
- [pending] 目标集群部署/联调待提供 namespace、镜像仓库、Scheduler URL、RBAC、对象存储 endpoint/bucket 与网络策略

## Round 023 — 引擎下拉与 Mock 环境日志 — 2026-11-17
- [fix] Binary 引擎下拉改为受控浮层，固定显示在输入框下方，支持输入自定义 binary 路径
- [feat] tools/mock/run_task.py 将执行器注入的全部环境变量写入 LOG_DIR/env-{case_run_id}.log
- [test] 跑通 6-case mock 任务并生成 6 份环境日志，覆盖 TASK_ID/CASE_RUN_ID/SCENARIO_URI/OUTPUT_DIR/LOG_DIR/SEED 等

## Round 022 — 发起仿真 RuntimeConfig 调整 — 2026-11-17
- [feat] 发起仿真页移除 Metric keys 输入，Metric 由 Scenario 内嵌配置驱动
- [feat] Binary 改为可输入引擎名或自定义本地 binary 路径；`.py` 自动用 Python 执行
- [docs] 页面增加 args 模板变量说明：SCENARIO_URI/OUTPUT_DIR/SEED/LOG_DIR
- [test] 自定义 binary 任务实测执行成功

## Round 021 — 数字 Metric ID 与 Scenario 内嵌 Metric — 2026-11-13
- [breaking] Metric ID 改为分类数字段并自动递增：1001+/2001+/3001+/4001+/5001+
- [data] 现有 Metric 重编号到数字段，删除测试指标并更新 Scenario DB 投影
- [breaking] Scenario.metrics 改为 metric.json 完整对象，移除 enabled/metric_def_id/metric_def_ver/config 包装
- [feat] 场景创建/编辑直接编辑内嵌 Metric 配置；旧版本文件读取时自动归一化
- [feat] Metric 新建不填 ID，后端按类型分类自动分配
- [test] 增加数值 ID 分配、Scenario 新 metrics 结构断言；60 passed

## Round 020 — 侧边栏路由高亮修复 — 2026-11-13
- [fix] 侧边栏所有菜单改为精确匹配，访问 /scenarios/new 时只高亮“场景创建”，不再同时高亮“场景列表”
- [fix] /tasks/new、/tasks/:id 也不会误高亮任务列表

## Round 019 — 创建场景时编辑 Metric — 2026-11-13
- [feat] 场景创建页直接选择 Metric 定义、增删多个 Metric，并编辑完整 config JSON 后一次性保存 Scenario
- [feat] 默认加载第一个 Metric 配置；JSON 预览实时更新；config JSON 错误阻止提交
- [test] 浏览器实测创建场景时修改 Metric ret=pass→fail，保存后 v1 配置正确落库

## Round 018 — Metric 编辑与删除 — 2026-11-13
- [feat] Metric 详情新增管理员「编辑 / 删除」操作
- [feat] 编辑加载原定义并生成新版本（v1 → v2），列表只展示每个 id 的最新版本
- [feat] 删除为软删除/废弃，确认后从默认定义列表移除
- [test] 增加 Metric 更新版本、废弃及列表过滤测试；浏览器实测编辑 v2、删除均成功

## Round 017 — 导入实际 Metric 与配置展示 — 2026-11-13
- [data] 导入 6 个实际 Metric 定义（id: 18/33/38/39/920/37139），覆盖 safety/navigation/comfort/compliance 四类
- [data] 补齐模板 15/21/22/27/87 和类型 compliance.steering/compliance.dlp
- [chore] 删除测试指标 demo.ui_metric、safety.json.ui
- [feat] Metric 详情 JSON 隐藏 trigger_templates/function_templates，仅展示实际 trigger_functions/functions 配置
- [tool] 新增 scripts/import_metrics.py，支持从 metric JSON 文件导入并保留原 id

## Round 016 — Metric JSON 去掉 type_id — 2026-11-13
- [fix] Metric JSON 展示移除 `type_id`；数据库/接口内部仍保留用于类型树分组
- [docs] 明确 id 为定义唯一键，type_id 为类型外键

## Round 015 — 精简 Metric JSON — 2026-11-13
- [fix] Metric 定义接口与页面 JSON 移除 `type_name`、`category_name`，保留 `type_id`、`category_id`
- [test] 增加字段移除断言；59 passed

## Round 014 — Metric JSON 配置管理 — 2026-11-13
- [breaking] metric_def 新增 `trigger_functions` / `functions` JSONB 规则字段（migration 008），兼容原模板引用
- [feat] Metric 管理页改为“已有定义列表 + 选中 JSON 配置”，移除无意义的 params_schema 预览和模板 Schema 页签
- [feat] 新增 Metric 时 trigger_functions / trigger_ops / functions（及 ops）按 JSON 编辑
- [feat] 场景创建引用 Metric 定义时优先复制定义中的规则 JSON，而非仅 env_example
- [contract] 契约升级 v2.2，存储规范同步 metric_def 内嵌规则 JSON
- [test] 新增 Metric 定义 JSON 持久化与场景配置复用测试

## Round 013 — Metric 新增入口与管理员权限 — 2026-11-13
- [feat] Metric 管理页新增「新增 Metric」入口，仅管理员/超级管理员可见
- [feat] 支持新增 Metric 定义：ID、名称、版本、类型、level、run_mode、ret/action、触发/函数模板
- [security] Metric 分类/类型/模板/定义的写接口统一要求管理员权限，普通用户返回 403
- [test] 增加普通用户创建 Metric 被拒绝测试；58 passed

## Round 012 — 移除 Scenario.extract — 2026-11-13
- [breaking] Scenario source 移除 `extract`，片段范围统一使用 `time_window.start_ts/end_ts`
- [feat] 场景创建/编辑页删除“片段开始/结束”重复输入，只保留 start_ts / trigger_ts / end_ts
- [compat] 后端接收旧 payload 时会丢弃 `extract`；API 响应不再返回该字段
- [compat] 已发布历史版本文件保持不可变，新版本不再写入 extract
- [test] 增加旧 extract 输入丢弃测试；58 passed

## Round 011 — rsclbag 默认格式 — 2026-11-13
- [feat] 场景数据源格式新增 `rsclbag`，并设为后端模型与前端创建页默认格式
- [feat] 创建/编辑页格式选项为 rsclbag、mcap、bag、parquet
- [test] 增加场景数据源默认格式测试；57 passed

## Round 010 — 管理员路由与前端托管开关 — 2026-11-13
- [fix] 普通用户不显示「账号与额度」菜单，直接访问 `/admin/users` 自动跳回场景列表
- [feat] 新增 `SIM_SERVE_FRONTEND`（默认 1）；设为 0 时后端只提供 API/docs
- [docs] 说明前端 5173 与后端 8000 默认显示同一 SPA 的原因

## Round 009 — 账号、权限额度与场景集可见性 — 2026-11-13
- [feat] 新增 `sim_user` / `sim_session` 账号系统，PBKDF2 密码哈希、Bearer 会话登录
- [feat] 内置超级管理员 `df_sim` / `df@sim_007`（最高 P9，额度 96 cases / 192 CPU / 768GB / 12 GPU）
- [feat] 管理员账号与额度页面；可配置角色、状态、最高优先级、并发及 CPU/内存/GPU 额度
- [feat] 任务提交校验账号最高优先级；调度领取校验账号并发与资源额度
- [feat] 场景创建自动记录 owner/created_by 并展示创建人
- [feat] 场景集新增 public/private 可见性；列表公共/私有切换；派方可选择可见性
- [security] 私有场景集仅 owner/管理员可读，修改/冻结仅 owner/管理员
- [migration] 新增 007_accounts_visibility.sql
- [test] 账号登录、用户额度、优先级拒绝、公共/私有可见性测试；56 passed

## Round 008 — 标签合法性校验 — 2026-11-13
- [feat] 标签仅允许中文、字母、数字、下划线和短横线，长度 1~64
- [feat] 拒绝 AND/OR 保留字及 &、|、括号、空格、逗号等特殊字符；创建/编辑页实时提示并禁用保存
- [fix] Pydantic 校验错误 ctx 中的 ValueError 无法 JSON 序列化，导致 422 变成 500；已安全序列化
- [test] 增加非法/保留标签、中文合法标签与 422 响应回归测试；52 passed

## Round 007 — 标签表达式筛选 — 2026-11-13
- [feat] 新增项目标签列表接口 `GET /tags`，返回标签及使用次数，支持搜索
- [feat] 场景列表与场景集创建筛选改为已有标签下拉框（可搜索、可点选追加）
- [feat] 标签表达式支持 `A&B|C`、`A&B&C`、括号，`&` 优先于 `|`
- [api] `GET /scenarios` 新增 `tag_expr`，保留 `tags/tag_mode/tag` 兼容
- [test] 增加表达式解析、优先级、非法表达式和三标签组合集成测试；41 passed

## Round 006 — 多标签筛选 — 2026-11-13
- [feat] 场景列表与场景集创建筛选支持多个标签（逗号分隔）
- [feat] 标签匹配支持 AND（同时满足）与 OR（任一满足）
- [api] `GET /scenarios` 新增重复 `tags` 参数与 `tag_mode=and|or`，保留单 `tag` 兼容
- [test] 增加多标签 AND/OR 集成测试，最终 32 passed

## Round 005 — 场景集名称 — 2026-11-13
- [feat] 创建场景集时填写自定义名称；创建成功后名称输入重置为新的默认值
- [feat] 派生场景集改为先填写来源信息与新名称，再确认派生
- [test] 浏览器实测创建“自定义名称测试集”、派生“自定义派生名称”成功

## Round 004 — 场景完整编辑 — 2026-11-13
- [feat] 场景详情页展示完整元信息、数据源、时间窗、Metric config、extra、版本历史和完整 JSON 预览
- [feat] 支持修改 trigger_ts、start_ts/end_ts、数据源、Metric config、alias、启停及新增/移除 Metric
- [feat] 保存时按当前版本生成不可变新版本（vN → vN+1），保留历史版本
- [test] 浏览器实测 场景-006 v2 → v3：trigger_ts=90000，加速度阈值 -3 → -3.5，checksum 更新，v1/v2 保留

## Round 003 — 场景集版本选择与筛选 — 2026-11-13
- [feat] 创建场景集时可按场景 ID / 标签筛选场景，并逐个指定成员版本（v1/v2/历史版本）
- [feat] 成员列表返回并显示场景名称、scenario_id 和锁定版本
- [fix] 后端校验成员引用的场景版本必须存在且 `publish_state=published`
- [test] 增加旧版本锁定、非法版本拒绝、成员名称接口测试；最终 31 passed

## Round 002 — Mock 联调 — 2026-11-12
- [feat] LocalExecutor 支持 `binary_id=mock`，调用 `tools/mock/run_task.py` 并派生稳定 case seed
- [fix] mock 失败/指标未通过原因回写；新增 case `outcome=pass|fail` 过滤与失败清单
- [fix] 任务详情 polling 同步刷新 CaseRun；KPI 周期刷新；终态任务隐藏暂停/取消
- [fix] 场景创建支持手动 Log URI/checksum/format；修复创建后 undefined 跳转与场景数刷新
- [fix] 场景集未冻结状态、队列中文状态、指标未通过徽标
- [test] 新增 mock 执行器集成测试，最终 30 passed；详见 evals/round-002-mock.md

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