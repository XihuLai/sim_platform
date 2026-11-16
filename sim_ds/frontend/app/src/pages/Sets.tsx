import { useState } from "react";
import { api } from "../api";
import { useAsync, useCursorList } from "../hooks";
import { SetScenarioPicker, type ScenarioVersionOption, type SelectedScenario } from "../components/SetScenarioPicker";
import { DeriveSetPanel } from "../components/DeriveSetPanel";
import { SetListPanel } from "../components/SetListPanel";
import { Card, PageHeader } from "../components/ui";
import { VirtualList } from "../components/VirtualList";
import type { Scenario, SetMember, SetSummary } from "../types";

function draftSetName(): string {
  return `场景集 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
}

export function Sets() {
  const [visibility, setVisibility] = useState<"public" | "private">("public");
  const sets = useCursorList<SetSummary>(
    (cursor) => api.sets.list({ visibility, cursor, size: 50 }),
    [visibility]
  );
  const [search, setSearch] = useState("");
  const [tagExpr, setTagExpr] = useState("");
  const scenarios = useAsync(
    () => api.scenarios.list({
      search,
      tag_expr: tagExpr,
      size: 200,
      status: "active"
    }),
    [search, tagExpr]
  );
  const [selected, setSelected] = useState<Record<string, SelectedScenario>>({});
  const [versions, setVersions] = useState<Record<string, ScenarioVersionOption[]>>({});
  const [setName, setSetName] = useState(draftSetName);
  const [newVisibility, setNewVisibility] = useState<"private" | "public">("private");
  const [deriveFrom, setDeriveFrom] = useState<SetSummary | null>(null);
  const [activeSet, setActiveSet] = useState<SetSummary | null>(null);
  const [members, setMembers] = useState<SetMember[]>([]);
  const [memberCursor, setMemberCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggleScenario(scenario: Scenario) {
    if (selected[scenario.id]) {
      const next = { ...selected };
      delete next[scenario.id];
      setSelected(next);
      return;
    }
    setSelected((current) => ({
      ...current,
      [scenario.id]: { scenario, version: scenario.version }
    }));
    if (!versions[scenario.id]) {
      try {
        const result = await api.scenarios.versions(scenario.id);
        setVersions((current) => ({
          ...current,
          [scenario.id]: result.items.map((item) => ({
            version: Number(item.version),
            publish_state: String(item.publish_state)
          }))
        }));
      } catch {
        // The current version remains selectable if history cannot be loaded.
      }
    }
  }

  function changeVersion(scenarioId: string, version: number) {
    setSelected((current) => {
      const entry = current[scenarioId];
      if (!entry) return current;
      return { ...current, [scenarioId]: { ...entry, version } };
    });
  }

  async function create() {
    const chosen = Object.values(selected);
    if (!setName.trim()) {
      setError("请填写场景集名称");
      return;
    }
    if (!chosen.length) return;
    setBusy(true);
    setError(null);
    try {
      await api.sets.create({
        name: setName.trim(),
        description: "由前端组合创建",
        members: chosen.map((entry, index) => ({
          scenario_id: entry.scenario.id,
          scenario_version: entry.version,
          sort_order: index
        })),
        project: localStorage.getItem("sim.project") || "default",
        visibility: newVisibility
      });
      setSelected({});
      setSetName(draftSetName());
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

  function openDerive(item: SetSummary) {
    setDeriveFrom(item);
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
        <SetScenarioPicker
          scenarios={scenarios.data?.items || []}
          loading={scenarios.loading}
          error={scenarios.error}
          name={setName}
          visibility={newVisibility}
          search={search}
          tagExpr={tagExpr}
          selected={selected}
          versions={versions}
          creating={busy}
          createError={error}
          onName={setSetName}
          onVisibility={setNewVisibility}
          onSearch={setSearch}
          onTagExpr={setTagExpr}
          onReload={scenarios.reload}
          onToggle={toggleScenario}
          onVersion={changeVersion}
          onCreate={create}
        />
        <SetListPanel
          sets={sets}
          visibility={visibility}
          onVisibility={setVisibility}
          onMembers={openMembers}
          onFreeze={freeze}
          onDerive={openDerive}
        />
      </div>
      {deriveFrom && (
        <DeriveSetPanel
          source={deriveFrom}
          onDone={() => {
            setDeriveFrom(null);
            sets.reload();
          }}
          onCancel={() => setDeriveFrom(null)}
        />
      )}
      {activeSet && (
        <Card>
          <div className="card-head">
            <h2>{activeSet.name} · 成员（v{activeSet.current_version}）</h2>
            <button className="btn tiny ghost" onClick={() => setActiveSet(null)}>关闭</button>
          </div>
          <VirtualList items={members} rowHeight={48} height={260} keyOf={(item) => item.scenario_id} onEnd={loadMembers} render={(item) => (
            <div className="member-row">
              <span>{item.scenario_name || item.scenario_id}</span>
              <code>{item.scenario_id}</code>
              <span>v{item.scenario_version}</span>
              <small>#{item.sort_order}</small>
            </div>
          )} />
          {memberCursor && <button className="btn ghost more" onClick={loadMembers}>加载更多成员</button>}
        </Card>
      )}
    </div>
  );
}
