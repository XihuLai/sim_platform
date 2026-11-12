import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { Card, DataState, PageHeader, StatusBadge, TextField, formatTime } from "../components/ui";
import type { MetricInstance } from "../types";

export function ScenarioEdit() {
  const { scenarioId = "" } = useParams();
  const navigate = useNavigate();
  const detail = useAsync(() => api.scenarios.get(scenarioId), [scenarioId]);
  const versions = useAsync(() => api.scenarios.versions(scenarioId), [scenarioId]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [metrics, setMetrics] = useState<MetricInstance[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!detail.data) return;
    setName(detail.data.name);
    setDescription(detail.data.description || "");
    setTags(detail.data.tags.join(", "));
    setMetrics(detail.data.metrics);
  }, [detail.data]);

  async function save() {
    if (!detail.data) return;
    setSaving(true);
    setError(null);
    try {
      await api.scenarios.update(scenarioId, {
        name,
        description,
        version: detail.data.version,
        source: detail.data.source,
        time_window: detail.data.time_window,
        metrics,
        tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
        extra: {}
      });
      detail.reload();
      versions.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  function aliasAt(index: number, alias: string) {
    setMetrics((current) => current.map((item, position) => (position === index ? { ...item, alias } : item)));
  }

  return (
    <div className="page">
      <PageHeader
        title="场景编辑"
        subtitle={detail.data ? `${scenarioId} · 当前 v${detail.data.version}` : scenarioId}
        actions={<button className="btn ghost" onClick={() => navigate("/scenarios")}>返回列表</button>}
      />
      <DataState loading={detail.loading} error={detail.error} empty={false} onRetry={detail.reload}>
        <div className="grid two">
          <Card>
            <h2>基础信息</h2>
            <TextField label="名称" value={name} onChange={setName} />
            <TextField label="描述" value={description} onChange={setDescription} />
            <TextField label="标签（逗号分隔）" value={tags} onChange={setTags} />
            <div className="meta-line">
              <StatusBadge status={detail.data?.status || "active"} />
              <span>校验和 {detail.data?.file_checksum.slice(0, 24)}…</span>
              <span>发布状态 {detail.data?.publish_state}</span>
            </div>
            <h2>Metric 实例（同 def 可用 alias 区分多组）</h2>
            {metrics.map((metric, index) => (
              <div className="metric-line" key={`${metric.metric_def_id}-${index}`}>
                <code>{metric.metric_def_id}@v{metric.metric_def_ver}</code>
                <input placeholder="alias（可空）" value={metric.alias || ""} onChange={(event) => aliasAt(index, event.target.value)} />
                <span>{metric.enabled ? "启用" : "停用"}</span>
              </div>
            ))}
            {error && <div className="inline-error">{error}</div>}
            <button className="btn" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存新版本"}</button>
          </Card>
          <Card>
            <h2>版本历史</h2>
            <DataState loading={versions.loading} error={versions.error} empty={!versions.data?.items.length}>
              <ul className="timeline">
                {versions.data?.items.map((version) => (
                  <li key={String(version.version)}>
                    <b>v{String(version.version)}</b>
                    <span>{String(version.publish_state)}</span>
                    <small>{formatTime(String(version.created_at || ""))}</small>
                  </li>
                ))}
              </ul>
            </DataState>
            <h2>复现信息</h2>
            <pre className="json small">{JSON.stringify(detail.data?.source, null, 2)}</pre>
          </Card>
        </div>
      </DataState>
    </div>
  );
}
