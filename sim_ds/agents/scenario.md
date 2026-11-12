# Scenario Agent

## 角色
场景域后端：录包→Case→标签→Metric（五层）→ScenarioSet 全链路。

## 只读
docs/CONTRACT*.md、docs/PLAN.md

## 可写
backend/scenario/**、migrations/（经 Architect 评审）、backend/tests/scenario/**

## 必做
1. 录包元数据解析（mcap/bag/parquet；可先桩，但接口就绪）：channels/时长/可裁剪区间。
2. Case 创建：选 log + clip 时间窗 + trigger + metric 实例 + 标签 + 描述
   → Scenario JSON 落文件 + DB 索引。
3. 编辑：version+1，写 scenarios/{id}/v{n}.json + scenario_version；保留历史。
4. Metric 五层：
   - category（固定 5 类，禁止运行时增删）
   - type（树形，parent_id；新增不改表）
   - template（template_id，kind=trigger|function，env_schema；新增不改表）
   - def（(id,version)，规则组合 trigger_templates/function_templates/ops/ret/action
     + 元信息 level/business_type/run_mode/is_global；schema 不兼容变更 version+1；
     删除改 deprecated）
   - instance（scenario_metric.config 存完整规则实例；同 def 多组靠 alias）
5. Metric 两级校验（写入前）：
   a) 结构校验：config 整体（trigger_functions/functions 数组、每项必须有
      template_id+env、ops 枚举 AND/OR、ret 枚举 pass/fail、action 字符串、
      level 枚举、is_global 布尔）。
   b) 动态校验：每个 env 按 template_id 取 metric_template.env_schema 校验；
      template_id 必须存在且 kind 匹配（trigger_functions 用 trigger，
      functions 用 function）；def 声明的 required template 必须出现。
   c) 任一级失败拒绝写入，返回字段路径 + 原因（METRIC_CONFIG_INVALID）。
6. ScenarioSet：组合/版本化/冻结；成员锁 scenario_version；>2000 成员分片
   （v{n}.meta.json + v{n}.members.{k}.json）；冻结后只读。
7. Pydantic v2 校验 Scenario JSON；checksum(sha256) 落 DB；巡检以文件为准。
8. 标签体系：category + parent_id 树形；新增标签不改表。
9. 写入时序：先 DB 事务（version+1、全量替换 scenario_metric、写 version 行），
   后写文件并回填 checksum；文件失败标 dirty 由 DB 重建。
10. 按 template_id 反查场景：config GIN 索引查询（idx_scn_metric_cfg）。

## 禁止
- 大文件全量入内存；Scenario 内联二进制或内联 template/def 定义。
- 绕过两级校验直接写文件/DB；只做结构校验不做 env 动态校验。
- 在 DB 存大 JSON（config >16KB 必须拆 alias 或检查设计）。
- 成员只写 scenario_id 不写 scenario_version。
- 修改 metric_category 集合（固定 5 类）。

## 自检
lint + mypy + pytest：CRUD/版本/冻结/checksum 巡检/Set 分片/Metric 五层/
template env_schema 动态校验/同 def 多 alias/定义版本锁定/按 template_id 反查/
config 两级校验失败路径/固定 5 类不可增删。
- test_duration_ms_is_generated_not_writable   # 写入 duration_ms 报错
- test_duration_ms_auto_updates_on_end_ts      # 改 end_ts 后 duration_ms 同步
- test_duration_ms_equals_eval_window          # = end_ts - start_ts，非裁剪时长

### scenario.duration_ms 派生规则
- 定义：duration_ms = time_window.end_ts - time_window.start_ts（评估窗口时长）。
- 实现：PG 生成列 GENERATED ALWAYS AS (end_ts - start_ts) STORED；
  应用层禁止写入；SQLite 降级用应用层维护 + 30s 对账。
- 不含裁剪缓冲：裁剪数据时长 = duration_ms + 2*clip_padding_ms，
  需要时现算，不落列。
- 索引：idx_scn_duration(duration_ms) WHERE status='active'，服务列表排序/筛选。