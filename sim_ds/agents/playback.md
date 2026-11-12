# Playback Agent

## 角色
播放域：raw log 与 sim 输出统一为 DataSource，建索引，提供分片/单帧接口，
实现播放器组件。基于~/repos/l29_node_visualizer这个项目进行开发，尽可能的复用该项目，如果需要其它信息，可以查看~/repos下其它仓库。

## 只读
docs/CONTRACT*.md、docs/PLAN.md

## 可写
backend/playback/**、frontend/player/**、backend/tests/playback/**

## 必做（后端）
- DataSource 归一化：record 与 sim_output 都映射到 channels/duration/index。
- 异步建索引（POST /sources:index）：ts → chunk 偏移；进度可查；
  只对用户打开的 case 触发，禁止预建全量。
- 分片接口 chunk(channel, ts, span) 与 frame(channel, ts, idx)，按需返回。
- 大文件流式响应（Range）。
- 目录分片：/data/outputs/{task_id}/{case_run_id}/sources/ 与 logs/ 分开，
  单目录文件数 ≤10000。

## 必做（前端播放器）
- 时间轴 seek/播放/暂停/速率 0.25x~4x/逐帧。
- 多通道同步（video/pointcloud/timeseries/pose 按 sync_ts 对齐）。
- 对比模式 raw vs sim 双窗同步。
- 按需加载：预取 ±2s，滚动淘汰，内存目标 <500MB。
- 四态：空/加载/索引中/错误。

## 禁止
- 整段视频/点云 base64 入 JSON；seek 全量重拉；播放器与业务页面强耦合。

## 自检
lint + mypy + pytest（索引/分片/帧）+ 前端 build + 播放 e2e：
首帧<1s、seek<500ms（30min 源）、对比同步误差<1 帧。