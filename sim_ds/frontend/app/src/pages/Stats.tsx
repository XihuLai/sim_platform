import { useState } from "react";
import { api } from "../api";
import { useAsync } from "../hooks";
import { Card, DataState, PageHeader } from "../components/ui";

export function Stats() {
  const [days, setDays] = useState(30);
  const state = useAsync(() => api.userStats(days), [days]);

  return (
    <div className="page">
      <PageHeader
        title="数据统计"
        subtitle="按提交时间统计用户任务总量与 case 累计；管理员可查看全部用户，普通用户仅看自己"
        actions={
          <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
            <option value={7}>最近 7 天</option>
            <option value={30}>最近 30 天</option>
            <option value={90}>最近 90 天</option>
            <option value={365}>最近 365 天</option>
          </select>
        }
      />
      <DataState loading={state.loading} error={state.error} empty={false} onRetry={state.reload}>
        <div className="grid three">
          <Card>
            <h2>任务总量</h2>
            <div className="big-number">{state.data?.totals.tasks || 0}</div>
            <p className="muted">最近 {days} 天提交的任务数</p>
          </Card>
          <Card>
            <h2>Case 累计</h2>
            <div className="big-number">{state.data?.totals.cases || 0}</div>
            <p className="muted">按任务展开 case 数累计</p>
          </Card>
          <Card>
            <h2>执行成功 / 指标通过</h2>
            <div className="big-number">
              {state.data?.totals.succeeded || 0}
              <small className="muted"> / {state.data?.totals.passed || 0}</small>
            </div>
            <p className="muted">执行成功 case / 指标通过 case</p>
          </Card>
        </div>
        <Card>
          <h2>用户任务统计</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th>用户</th>
                <th>任务数</th>
                <th>Case 数</th>
                <th>执行成功</th>
                <th>指标通过</th>
              </tr>
            </thead>
            <tbody>
              {state.data?.items.map((row) => (
                <tr key={row.owner}>
                  <td>{row.owner}</td>
                  <td>{row.tasks}</td>
                  <td>{row.cases}</td>
                  <td>{row.succeeded}</td>
                  <td>{row.passed}</td>
                </tr>
              ))}
              {!state.data?.items.length && (
                <tr><td colSpan={5} className="muted">该时间段暂无任务</td></tr>
              )}
            </tbody>
          </table>
        </Card>
      </DataState>
    </div>
  );
}
