import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useCursorList } from "../hooks";
import { Card, DataState, PageHeader, PriorityBadge, Progress, StatusBadge, Tabs, formatTime } from "../components/ui";
import { VirtualList } from "../components/VirtualList";
import type { Task } from "../types";

const FILTERS = [
  { value: "all", label: "全部" },
  { value: "running", label: "运行中" },
  { value: "queued", label: "排队" },
  { value: "expanding", label: "展开中" },
  { value: "succeeded", label: "成功" },
  { value: "failed", label: "失败" }
] as const;

function requestId(): string {
  return globalThis.crypto?.randomUUID?.() || `web-${Date.now()}`;
}

export function TaskList() {
  const [status, setStatus] = useState<(typeof FILTERS)[number]["value"]>("all");
  const [search, setSearch] = useState("");
  const tasks = useCursorList<Task>(
    (cursor) => api.tasks.list({ status: status === "all" ? "" : status, search, cursor, size: 50 }),
    [status, search]
  );
  const [message, setMessage] = useState<string | null>(null);

  async function control(task: Task, command: "pause" | "resume" | "cancel") {
    if (command === "cancel" && !confirm(`确认取消任务「${task.name}」？`)) return;
    try {
      await api.tasks.control(task.task_id, command, requestId(), "web");
      setMessage(`已提交 ${command} 请求：${task.task_id}`);
      tasks.reload();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "控制失败");
    }
  }

  return (
    <div className="page">
      <PageHeader title="任务列表" subtitle="状态读 task_summary 预聚合；控制请求持久化，幂等重放" actions={<Link className="btn" to="/tasks/new">发起仿真</Link>} />
      <Card className="filters">
        <input placeholder="搜索任务名称或 ID" value={search} onChange={(event) => setSearch(event.target.value)} />
        <button className="btn ghost" onClick={tasks.reload}>刷新</button>
        <span className="muted">已加载 {tasks.items.length} 条</span>
      </Card>
      <Tabs value={status} options={FILTERS.map((item) => ({ value: item.value, label: item.label }))} onChange={setStatus} />
      {message && <div className="notice">{message}</div>}
      <Card>
        <DataState loading={tasks.loading} error={tasks.error} empty={tasks.items.length === 0} onRetry={tasks.reload}>
          <VirtualList
            items={tasks.items}
            rowHeight={112}
            height={520}
            keyOf={(item) => item.task_id}
            onEnd={tasks.loadMore}
            render={(task) => (
              <div className="task-row">
                <div className="task-main">
                  <strong><Link to={`/tasks/${task.task_id}`}>{task.name}</Link></strong>
                  <small>{task.task_id} · {task.set_name || task.set_id} v{task.set_version} · {formatTime(task.created_at)}</small>
                  <Progress value={task.progress} />
                </div>
                <PriorityBadge priority={task.priority} />
                <StatusBadge status={task.status} />
                <span className="counts">{task.pass_count} 通过 / {task.fail_count} 未通过</span>
                <div className="row-actions">
                  {task.status === "paused"
                    ? <button className="btn tiny" onClick={() => control(task, "resume")}>恢复</button>
                    : <button className="btn tiny ghost" onClick={() => control(task, "pause")}>暂停</button>}
                  <button className="btn tiny danger" onClick={() => control(task, "cancel")}>取消</button>
                  <Link className="btn tiny ghost" to={`/tasks/${task.task_id}/summary`}>结果</Link>
                </div>
              </div>
            )}
          />
        </DataState>
      </Card>
    </div>
  );
}
