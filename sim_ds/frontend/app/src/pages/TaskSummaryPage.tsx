import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAsync, useCursorList } from "../hooks";
import { BarChart, Donut } from "../components/Charts";
import { Card, DataState, PageHeader, StatusBadge, formatTime } from "../components/ui";
import { VirtualList } from "../components/VirtualList";
import type { CaseRun } from "../types";

const STATUS_LABEL: Record<string, string> = {
  queued: "排队", scheduled: "调度", running: "运行", paused: "暂停",
  succeeded: "成功", failed: "失败", canceled: "取消", timeout: "超时", worker_lost: "失联"
};

export function TaskSummaryPage() {
  const { taskId = "" } = useParams();
  const summary = useAsync(() => api.tasks.summary(taskId), [taskId]);
  const failures = useCursorList<CaseRun>(
    (cursor) => api.tasks.cases(taskId, { status: "failed", cursor, size: 50 }),
    [taskId]
  );

  return (
    <div className="page">
      <PageHeader
        title="结果汇总"
        subtitle={summary.data?.task.name || taskId}
        actions={<Link className="btn ghost" to={`/tasks/${taskId}`}>返回任务</Link>}
      />
      <DataState loading={summary.loading} error={summary.error} empty={false} onRetry={summary.reload}>
        <Card className="conclusion">
          <p>{summary.data?.text}</p>
          <div className="stat-pills">
            <span>总 cases <b>{summary.data?.task.total_cases}</b></span>
            <span>通过率 <b>{summary.data?.pass_rate}%</b></span>
            <span>通过 <b>{summary.data?.task.pass_count}</b></span>
            <span>未通过 <b>{summary.data?.task.fail_count}</b></span>
            <span>状态 <StatusBadge status={summary.data?.task.status || ""} /></span>
          </div>
        </Card>
        <div className="grid two">
          <Card>
            <h2>状态分布</h2>
            <Donut
              items={(summary.data?.charts.status || []).map((row) => ({
                key: row.key,
                value: row.value,
                label: STATUS_LABEL[row.key] || row.key
              }))}
              centerLabel="cases"
            />
          </Card>
          <Card>
            <h2>Metric 通过数</h2>
            <BarChart
              items={(summary.data?.charts.metrics || []).map((row) => ({
                key: row.key,
                value: row.pass_cnt,
                label: `${row.key} (${row.cnt})`
              }))}
              unit=""
            />
            <p className="muted">每项指标：通过数 / 总样本；完整 p95 由后台预聚合任务更新。</p>
          </Card>
        </div>
        <Card>
          <div className="card-head">
            <h2>失败清单（游标分页）</h2>
            <span className="muted">点击播放入口可进入 Playback</span>
          </div>
          <DataState loading={failures.loading} error={failures.error} empty={failures.items.length === 0} onRetry={failures.reload}>
            <VirtualList
              items={failures.items}
              rowHeight={54}
              height={260}
              keyOf={(item) => item.case_run_id}
              onEnd={failures.loadMore}
              render={(item) => (
                <div className="failure-row">
                  <code>{item.case_run_id}</code>
                  <span>{item.scenario_id}</span>
                  <StatusBadge status={item.status} />
                  <small>{formatTime(item.finished_at)}</small>
                  <Link className="link" to={`/playback?case=${item.case_run_id}`}>播放</Link>
                </div>
              )}
            />
          </DataState>
          {failures.next && <button className="btn ghost more" onClick={failures.loadMore}>加载更多失败</button>}
        </Card>
      </DataState>
    </div>
  );
}
