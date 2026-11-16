import { useMemo, useState } from "react";
import { api } from "../api";
import { useAsync } from "../hooks";
import { Card, DataState, PageHeader, StatusBadge } from "../components/ui";
import { MetricDefForm } from "../components/MetricDefForm";
import { currentUser } from "../auth";
import type { MetricDef } from "../types";

export function Metrics() {
  const [selected, setSelected] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<MetricDef | null>(null);
  const [message, setMessage] = useState("");
  const user = currentUser();
  const isAdmin = Boolean(user?.admin) || user?.role === "admin" || user?.role === "super_admin";
  const state = useAsync(async () => {
    const [categories, types, defs] = await Promise.all([
      api.metrics.categories(),
      api.metrics.types(),
      api.metrics.defs()
    ]);
    return {
      categories: categories.items,
      types: types.items,
      defs: defs.items
    };
  }, []);
  const latestDefs = useMemo(() => {
    const byId = new Map<string, MetricDef>();
    for (const definition of state.data?.defs || []) {
      const current = byId.get(definition.id);
      if (!current || definition.version > current.version) byId.set(definition.id, definition);
    }
    return Array.from(byId.values());
  }, [state.data]);
  const activeDef = useMemo(
    () => latestDefs.find((item) => item.id === selected) || latestDefs[0],
    [latestDefs, selected]
  );
  const metricJson = useMemo(() => {
    if (!activeDef) return null;
    const view: Record<string, unknown> = { ...activeDef };
    delete view.type_id;
    delete view.trigger_templates;
    delete view.function_templates;
    return view;
  }, [activeDef]);

  return (
    <div className="page">
      <PageHeader
        title="Metric 管理"
        subtitle="查看已有 Metric 定义及其 JSON 配置；新增 Metric 用 JSON 编辑 trigger_functions / trigger_ops / functions"
        actions={isAdmin ? <button className="btn" onClick={() => setCreating(true)}>新增 Metric</button> : undefined}
      />
      <DataState loading={state.loading} error={state.error} empty={false} onRetry={state.reload}>
        {(creating || editing) && (
          <MetricDefForm
            key={editing?.id || "new"}
            types={state.data?.types || []}
            initial={editing || undefined}
            onCancel={() => {
              setCreating(false);
              setEditing(null);
            }}
            onCreated={(id) => {
              setCreating(false);
              setEditing(null);
              setSelected(id);
              setMessage("Metric 已保存");
              state.reload();
            }}
          />
        )}
        {message && <div className="notice">{message}</div>}
        <div className="grid two">
          <Card>
            <h2>已有 Metric 定义</h2>
            <div className="metric-tree">
              {state.data?.categories.map((category) => (
                <div key={String(category.id)} className="tree-group">
                  <strong>{String(category.name)} <small>{String(category.id)}</small></strong>
                  {state.data?.types.filter((type) => type.category_id === category.id).map((type) => {
                    const defs = latestDefs.filter((definition) => definition.type_id === type.id);
                    if (!defs.length) return null;
                    return (
                      <div key={type.id} className="tree-type">
                        <span>{type.name}</span>
                        {defs.map((definition) => (
                          <button
                            key={`${definition.id}@${definition.version}`}
                            className={`tree-def ${activeDef?.id === definition.id ? "active" : ""}`}
                            onClick={() => setSelected(definition.id)}
                          >
                            {definition.name}
                            <small>v{definition.version}</small>
                          </button>
                        ))}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <div className="card-head">
              <h2>Metric JSON 配置</h2>
              {activeDef && isAdmin && (
                <div className="row-actions">
                  <button className="btn tiny" onClick={() => { setEditing(activeDef); setCreating(false); }}>编辑</button>
                  <button
                    className="btn tiny danger"
                    onClick={async () => {
                      if (!confirm(`确认删除 Metric「${activeDef.name}」？删除后标记为废弃。`)) return;
                      await api.metrics.deleteDef(activeDef.id);
                      setSelected("");
                      setMessage(`Metric ${activeDef.id} 已删除/废弃`);
                      state.reload();
                    }}
                  >
                    删除
                  </button>
                </div>
              )}
            </div>
            {activeDef ? (
              <>
                <div className="meta-line">
                  <code>{activeDef.id}@v{activeDef.version}</code>
                  <StatusBadge status={activeDef.status} />
                  <span>level {activeDef.level || "—"}</span>
                  <span>{activeDef.business_type || "—"}</span>
                  <span>{activeDef.run_mode || "async"}</span>
                </div>
                <pre className="json">{JSON.stringify(metricJson, null, 2)}</pre>
              </>
            ) : <p className="muted">暂无 Metric 定义</p>}
          </Card>
        </div>
      </DataState>
    </div>
  );
}
