import { useState } from "react";
import { api } from "../api";
import { useAsync, useCursorList } from "../hooks";
import { Card, DataState, PageHeader, StatusBadge, formatTime } from "../components/ui";
import { VirtualList } from "../components/VirtualList";
import type { Scenario, SetMember, SetSummary } from "../types";

export function Sets() {
  const sets = useCursorList<SetSummary>((cursor) => api.sets.list({ cursor, size: 50 }), []);
  const scenarios = useAsync(() => api.scenarios.list({ size: 100, status: "active" }), []);
  const [selected, setSelected] = useState<string[]>([]);
  const [activeSet, setActiveSet] = useState<SetSummary | null>(null);
  const [members, setMembers] = useState<SetMember[]>([]);
  const [memberCursor, setMemberCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(id: string) {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function create() {
    if (!selected.length) return;
    setBusy(true);
    setError(null);
    try {
      const chosen = scenarios.data?.items.filter((item) => selected.includes(item.id)) || [];
      await api.sets.create({
        name: `场景集 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`,
        description: "由前端组合创建",
        members: chosen.map((item, index) => ({ scenario_id: item.id, scenario_version: item.version, sort_order: index })),
        project: localStorage.getItem("sim.project") || "default"
      });
      setSelected([]);
      sets.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function freeze(item: SetSummary) {
    if (!confirm(`确认冻结「${item.name}」？冻结后不可修改，只能派生。`)) return;
    await api.sets.freeze(item.id);
    sets.reload();
  }

  async function derive(item: SetSummary) {
    await api.sets.derive(item.id, { name: `${item.name}-派生` });
    sets.reload();
  }

  async function openMembers(item: SetSummary) {
    setActiveSet(item);
    const page = await api.sets.members(item.id);
    setMembers(page.items);
    setMemberCursor(page.next_cursor);
  }

  async function loadMembers() {
    if (!activeSet || !memberCursor) return;
    const page = await api.sets.members(activeSet.id, memberCursor);
    setMembers((current) => [...current, ...page.items]);
    setMemberCursor(page.next_cursor);
  }

  return (
    <div className="page">
      <PageHeader title="场景集管理" subtitle="版本快照落文件；冻结生成不可变版本，任务只能引用冻结版本" />
      <div className="grid two">
        <Card>
          <h2>创建场景集</h2>
          <DataState loading={scenarios.loading} error={scenarios.error} empty={!scenarios.data?.items.length}>
            <div className="check-grid">
              {scenarios.data?.items.map((scenario: Scenario) => (
                <label key={scenario.id} className="check-row">
                  <input type="checkbox" checked={selected.includes(scenario.id)} onChange={() => toggle(scenario.id)} />
                  <span>{scenario.name}</span>
                  <small>v{scenario.version}</small>
                </label>
              ))}
            </div>
          </DataState>
          <button className="btn" onClick={create} disabled={busy || !selected.length}>
            {busy ? "创建中…" : `创建场景集（已选 ${selected.length}）`}
          </button>
          {error && <div className="inline-error">{error}</div>}
        </Card>
        <Card>
          <h2>场景集列表</h2>
          <DataState loading={sets.loading} error={sets.error} empty={sets.items.length === 0} onRetry={sets.reload}>
            <VirtualList
              items={sets.items}
              rowHeight={104}
              height={420}
              keyOf={(item) => item.id}
              onEnd={sets.loadMore}
              render={(item) => (
                <div className="set-row">
                  <div>
                    <strong>{item.name}</strong>
                    <small>v{item.current_version} · {item.member_count} 成员 · {formatTime(item.created_at)}</small>
                  </div>
                  <StatusBadge status={item.frozen ? "succeeded" : "queued"} />
                  <div className="row-actions">
                    <button className="btn tiny ghost" onClick={() => openMembers(item)}>成员</button>
                    {!item.frozen && <button className="btn tiny" onClick={() => freeze(item)}>冻结</button>}
                    <button className="btn tiny ghost" onClick={() => derive(item)}>派生</button>
                  </div>
                </div>
              )}
            />
          </DataState>
        </Card>
      </div>
      {activeSet && (
        <Card>
          <div className="card-head">
            <h2>{activeSet.name} · 成员（v{activeSet.current_version}）</h2>
            <button className="btn tiny ghost" onClick={() => setActiveSet(null)}>关闭</button>
          </div>
          <VirtualList items={members} rowHeight={44} height={240} keyOf={(item) => item.scenario_id} onEnd={loadMembers} render={(item) => (
            <div className="member-row"><code>{item.scenario_id}</code><span>v{item.scenario_version}</span><small>#{item.sort_order}</small></div>
          )} />
          {memberCursor && <button className="btn ghost more" onClick={loadMembers}>加载更多成员</button>}
        </Card>
      )}
    </div>
  );
}
