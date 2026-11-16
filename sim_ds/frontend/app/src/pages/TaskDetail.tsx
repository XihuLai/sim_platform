import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAsync, useCursorList, useInterval } from "../hooks";
import { Card, DataState, PageHeader, PriorityBadge, Progress, ResultBadge, StatusBadge, Tabs, formatTime } from "../components/ui";
import { VirtualList } from "../components/VirtualList";
import type { CaseRun } from "../types";

const FILTERS = [
  { value: "", label: "全部" },
  { value: "succeeded", label: "成功" },
  { value: "failed", label: "执行失败" },
  { value: "result_fail", label: "指标未通过" },
  { value: "running", label: "运行中" },
  { value: "queued", label: "排队" }
];

export function TaskDetail() {
  const { taskId = "" } = useParams();
  const taskState = useAsync(() => api.tasks.get(taskId), [taskId]);
  const [filter, setFilter] = useState("");
  const cases = useCursorList<CaseRun>(
    (cursor) =>
      api.tasks.cases(taskId, {
        status: filter === "result_fail" ? undefined : filter,
        outcome: filter === "result_fail" ? "fail" : undefined,
        cursor,
        size: 100
      }),
    [taskId, filter]
  );
  const [active, setActive] = useState<CaseRun | null>(null);
  const terminal = taskState.data && ["succeeded", "failed", "canceled"].includes(taskState.data.status);
  useInterval(() => {
    taskState.reload();
    cases.reload();
  }, terminal ? null : 3000);
  useEffect(() => {
    if (taskState.data?.status) cases.reload();
  }, [taskState.data?.status]);

  return (
    <div className="page">
      <PageHeader
        title={taskState.data?.name || "任务详情"}
        subtitle={taskId}
        actions={<Link className="btn" to={`/tasks/${taskId}/summary`}>结果汇总</Link>}
      />
      <DataState loading={taskState.loading} error={taskState.error} empty={false} onRetry={taskState.reload}>
        <Card className="task-hero">
          <div>
            <div className="meta-line">
              <StatusBadge status={taskState.data?.status || ""} />
              <PriorityBadge priority={taskState.data?.priority || 0} />
              <span>{taskState.data?.total_cases || 0} cases</span>
              <span>创建 {formatTime(taskState.data?.created_at)}</span>
            </div>
            <Progress value={taskState.data?.progress || 0} />
          </div>
          <div className="stat-pills">
            <span>成功 <b>{taskState.data?.counts.succeeded || 0}</b></span>
            <span>失败 <b>{taskState.data?.counts.failed || 0}</b></span>
            <span>排队 <b>{taskState.data?.counts.queued || 0}</b></span>
            <span>通过 <b>{taskState.data?.pass_count || 0}</b></span>
          </div>
        </Card>
        <Card>
          <div className="card-head">
            <h2>CaseRun 列表</h2>
            <Tabs value={filter} options={FILTERS} onChange={setFilter} />
          </div>
          <DataState loading={cases.loading} error={cases.error} empty={cases.items.length === 0} onRetry={cases.reload}>
            <VirtualList
              items={cases.items}
              rowHeight={54}
              height={420}
              keyOf={(item) => item.case_run_id}
              onEnd={cases.loadMore}
              render={(item) => (
                <button className={`case-row ${active?.case_run_id === item.case_run_id ? "active" : ""}`} onClick={() => setActive(item)}>
                  <code>{item.case_run_id}</code>
                  <span>{item.scenario_id} v{item.scenario_version}</span>
                  <ResultBadge status={item.status} metrics={item.metrics} />
                  <small>attempt {item.attempt}</small>
                  <small>{formatTime(item.finished_at)}</small>
                </button>
              )}
            />
          </DataState>
        </Card>
        {active && (
          <Card>
            <div className="card-head">
              <h2>Case 下钻 · {active.case_run_id}</h2>
              <Link className="btn tiny" to={`/playback?case=${active.case_run_id}`}>打开播放器</Link>
            </div>
            <div className="grid two">
              <div>
                <p>状态：<ResultBadge status={active.status} metrics={active.metrics} /> · attempt {active.attempt} · exit {active.exit_code ?? "—"}</p>
                <p>场景：{active.scenario_id} v{active.scenario_version}</p>
                <p>
                  失败原因：
                  {active.reason ||
                    (Object.values(active.metrics).some((metric) => metric.pass === false)
                      ? `指标未通过：${Object.entries(active.metrics)
                          .filter(([, metric]) => metric.pass === false)
                          .map(([key]) => key)
                          .join(", ")}`
                      : "无")}
                </p>
                <p>输出：<code>{active.output_uri || "—"}</code></p>
              </div>
              <pre className="json small">{JSON.stringify(active.metrics, null, 2)}</pre>
            </div>
          </Card>
        )}
      </DataState>
    </div>
  );
}
