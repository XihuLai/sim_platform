import { api } from "../api";
import { useAsync, useInterval } from "../hooks";
import { BarChart, Donut } from "../components/Charts";
import { Card, DataState, PageHeader, PriorityBadge, formatTime, statusLabel } from "../components/ui";

export function QueueBoard() {
  const queue = useAsync(() => api.tasks.queue(), []);
  const overview = useAsync(() => api.overview(), []);
  useInterval(() => {
    queue.reload();
    overview.reload();
  }, 5000);

  return (
    <div className="page">
      <PageHeader title="队列看板" subtitle="读预聚合 task_summary；每 5 秒刷新，不做 OFFSET 深翻页" />
      <DataState loading={queue.loading} error={queue.error} empty={false} onRetry={queue.reload}>
        <div className="grid three">
          <Card>
            <h2>队列深度</h2>
            <div className="big-number">{overview.data?.queue_depth ?? "—"}</div>
            <p className="muted">等待中 {overview.data?.queue_depth ?? 0} · 运行中 {overview.data?.running_cases ?? 0}</p>
            <h3>按状态</h3>
            <BarChart items={queue.data?.by_status.map((row) => ({ key: row.status, value: row.tasks, label: statusLabel(row.status) })) || []} unit=" 任务" />
          </Card>
          <Card>
            <h2>状态分布</h2>
            <Donut items={queue.data?.by_status.map((row) => ({ key: row.status, value: row.total_cases, label: statusLabel(row.status) })) || []} centerLabel="cases" />
          </Card>
          <Card>
            <h2>优先级等待</h2>
            <div className="priority-list">
              {queue.data?.by_priority.map((row) => (
                <div key={row.priority} className="priority-line">
                  <PriorityBadge priority={row.priority} />
                  <span>{row.tasks} 任务</span>
                  <b>{row.waiting} 等待</b>
                </div>
              ))}
              {!queue.data?.by_priority.length && <p className="muted">暂无排队任务</p>}
            </div>
            <h3>最早任务</h3>
            <p className="muted">{formatTime(queue.data?.by_status.map((row) => row.oldest_created).filter(Boolean).sort()[0])}</p>
          </Card>
        </div>
      </DataState>
    </div>
  );
}
