import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { MetricConfigEditor, type EditableMetric } from "../components/MetricConfigEditor";
import { editableFromScenario, scenarioMetricFromEditable } from "../scenarioMetrics";
import { ScenarioEditorForm, initialScenarioForm, type ScenarioFormState } from "../components/ScenarioEditorForm";
import { Card, DataState, PageHeader, StatusBadge, formatTime } from "../components/ui";
import { tagValidationError } from "../tags";

export function ScenarioEdit() {
  const { scenarioId = "" } = useParams();
  const navigate = useNavigate();
  const detail = useAsync(() => api.scenarios.get(scenarioId), [scenarioId]);
  const versions = useAsync(() => api.scenarios.versions(scenarioId), [scenarioId]);
  const catalog = useAsync(async () => {
    const [defs, templates] = await Promise.all([api.metrics.defs(), api.metrics.templates()]);
    return { defs: defs.items, templates: templates.items };
  }, []);
  const [form, setForm] = useState<ScenarioFormState>(initialScenarioForm);
  const [metrics, setMetrics] = useState<EditableMetric[]>([]);
  const [extraText, setExtraText] = useState("{}");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!detail.data) return;
    setForm({
      name: detail.data.name,
      description: detail.data.description || "",
      tags: detail.data.tags.join(", "),
      source: detail.data.source,
      timeWindow: {
        start_ts: String(detail.data.time_window.start_ts),
        end_ts: String(detail.data.time_window.end_ts),
        trigger_ts: String(detail.data.time_window.trigger_ts)
      }
    });
    setExtraText(JSON.stringify(detail.data.extra || {}, null, 2));
  }, [detail.data]);

  useEffect(() => {
    if (!detail.data) return;
    setMetrics(detail.data.metrics.map((metric) => editableFromScenario(metric, catalog.data?.defs || [])));
  }, [detail.data, catalog.data]);

  const nextVersion = (detail.data?.version || 0) + 1;
  const preview = useMemo(() => {
    const parsedMetrics = metrics.map((metric) => {
      try {
        return scenarioMetricFromEditable(metric, catalog.data?.defs || []);
      } catch {
        return { id: metric.metric_def_id, name: metric.metric_def_id, desc: "" };
      }
    });
    let extra: unknown = extraText;
    try {
      extra = JSON.parse(extraText || "{}");
    } catch {
      extra = "<invalid JSON>";
    }
    return {
      scenario_id: scenarioId,
      version: nextVersion,
      name: form.name,
      description: form.description,
      tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
      source: form.source,
      time_window: {
        start_ts: Number(form.timeWindow.start_ts),
        end_ts: Number(form.timeWindow.end_ts),
        trigger_ts: Number(form.timeWindow.trigger_ts)
      },
      metrics: parsedMetrics,
      extra
    };
  }, [scenarioId, nextVersion, form, metrics, extraText, catalog.data]);

  async function save() {
    if (!detail.data) return;
    const tagError = tagValidationError(form.tags);
    if (tagError) {
      setError(tagError);
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      for (const metric of metrics) {
        try {
          JSON.parse(metric.configText);
        } catch {
          throw new Error(`${metric.metric_def_id} 的 config JSON 格式错误`);
        }
      }
      const extra = JSON.parse(extraText || "{}");
      const updated = await api.scenarios.update(scenarioId, {
        name: form.name,
        description: form.description,
        version: detail.data.version,
        source: form.source,
        time_window: {
          start_ts: Number(form.timeWindow.start_ts),
          end_ts: Number(form.timeWindow.end_ts),
          trigger_ts: Number(form.timeWindow.trigger_ts)
        },
        metrics: metrics.map((metric) =>
          scenarioMetricFromEditable(metric, catalog.data?.defs || [])
        ),
        tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
        extra
      });
      setNotice(`已保存并生成 v${updated.version}（上一版本 v${detail.data.version}）`);
      detail.reload();
      versions.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="场景详情 / 编辑"
        subtitle={detail.data ? `${scenarioId} · 当前 v${detail.data.version}` : scenarioId}
        actions={<button className="btn ghost" onClick={() => navigate("/scenarios")}>返回列表</button>}
      />
      <DataState loading={detail.loading} error={detail.error} empty={false} onRetry={detail.reload}>
        <Card>
          <div className="meta-line">
            <span>ID <code>{scenarioId}</code></span>
            <StatusBadge status={detail.data?.status || "active"} />
            <span>当前 v{detail.data?.version}</span>
            <span>下一版本 v{nextVersion}</span>
            <span>校验和 {detail.data?.file_checksum.slice(0, 30)}…</span>
            <span>发布状态 {detail.data?.publish_state}</span>
            <span>owner {detail.data?.owner || "—"}</span>
            <span>project {detail.data?.project || "—"}</span>
            <span>创建 {formatTime(detail.data?.created_at)}</span>
            <span>更新 {formatTime(detail.data?.updated_at)}</span>
          </div>
          <p className="muted">修改 trigger_ts、时间窗、数据源或 Metric config 后点击保存，系统会生成新的不可变版本。</p>
        </Card>
        <div className="grid two">
          <div className="grid">
            <ScenarioEditorForm form={form} onChange={setForm} />
          </div>
          <div className="grid">
            <Card>
              <h2>Metric 实例与 config</h2>
              <p className="muted">可直接修改 trigger/functions env、阈值、action 等；支持同 def 多 alias。</p>
              <MetricConfigEditor
                metrics={metrics}
                definitions={catalog.data?.defs || []}
                templates={catalog.data?.templates || []}
                onChange={setMetrics}
              />
              {catalog.error && <div className="inline-error">Metric 定义加载失败：{catalog.error}</div>}
            </Card>
            <Card>
              <h2>额外信息 extra</h2>
              <label className="field">
                <span>JSON</span>
                <textarea rows={5} value={extraText} onChange={(event) => setExtraText(event.target.value)} />
              </label>
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
            </Card>
          </div>
        </div>
        <Card>
          <h2>完整 Scenario JSON 预览（保存后的 v{nextVersion}）</h2>
          <pre className="json">{JSON.stringify(preview, null, 2)}</pre>
        </Card>
        {error && <div className="inline-error">{error}</div>}
        {notice && <div className="notice">{notice}</div>}
        <div className="actions">
          <button className="btn" onClick={save} disabled={saving}>
            {saving ? "保存中…" : `保存并派生新版本 v${nextVersion}`}
          </button>
        </div>
      </DataState>
    </div>
  );
}
