import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { Card, DataState, PageHeader, TextField } from "../components/ui";
import { SourceEditor, type SourceDraft } from "../components/SourceEditor";
import { buildMetricConfig } from "../metricConfig";
import { MetricConfigEditor, toEditable, type EditableMetric } from "../components/MetricConfigEditor";
import { editableFromScenario, scenarioMetricFromEditable } from "../scenarioMetrics";
import { TAG_RULE_TEXT, tagValidationError } from "../tags";

export function ScenarioCreate() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const copyId = searchParams.get("copy") || "";
  const catalog = useAsync(async () => {
    const [defs, templates, sources] = await Promise.all([
      api.metrics.defs(),
      api.metrics.templates(),
      api.playback.list({ size: 50 })
    ]);
    return { defs: defs.items, templates: templates.items, sources: sources.items };
  }, []);

  const copySource = useAsync(
    () => (copyId ? api.scenarios.get(copyId) : Promise.resolve(null)),
    [copyId]
  );
  const [name, setName] = useState("城市路口-新场景");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState<SourceDraft>({
    sourceId: "",
    logId: "log-001",
    logUri: "",
    logChecksum: "sha256:demo",
    format: "rsclbag"
  });
  const [startTs, setStartTs] = useState("0");
  const [endTs, setEndTs] = useState("180000");
  const [trigger, setTrigger] = useState("60000");
  const [tags, setTags] = useState("cut-in, junction");
  const [extraText, setExtraText] = useState("{}");
  const [metrics, setMetrics] = useState<EditableMetric[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initialized = useRef(false);

  useEffect(() => {
    if (initialized.current || !catalog.data) return;
    const catalogData = catalog.data;
    if (copyId) {
      const source = copySource.data;
      if (!source) return;
      setName(`${source.name}-副本`);
      setDescription(source.description || "");
      setSource({
        sourceId: "",
        logId: source.source.log_id,
        logUri: source.source.log_uri,
        logChecksum: source.source.log_checksum,
        format: source.source.format as SourceDraft["format"]
      });
      setStartTs(String(source.time_window.start_ts));
      setEndTs(String(source.time_window.end_ts));
      setTrigger(String(source.time_window.trigger_ts));
      setTags(source.tags.join(", "));
      setExtraText(JSON.stringify(source.extra || {}, null, 2));
      setMetrics(source.metrics.map((metric) => editableFromScenario(metric, catalogData.defs)));
      initialized.current = true;
      return;
    }
    if (!catalogData.defs.length) return;
    const definition = catalogData.defs[0];
    setMetrics([
      toEditable({
        metric_def_id: definition.id,
        metric_def_ver: definition.version,
        alias: null,
        config: buildMetricConfig(definition, catalogData.templates),
        enabled: true
      })
    ]);
    initialized.current = true;
  }, [catalog.data, copySource.data, copyId]);

  const tagError = tagValidationError(tags);
  const payload = useMemo(() => {
    const metricPayload = metrics.map((metric) => {
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
      name,
      description,
      project: copySource.data?.project || localStorage.getItem("sim.project") || "default",
      source: {
        type: copySource.data?.source.type || "record",
        log_id: source.logId,
        log_uri: source.logUri,
        log_checksum: source.logChecksum,
        format: source.format
      },
      time_window: { start_ts: Number(startTs), end_ts: Number(endTs), trigger_ts: Number(trigger) },
      metrics: metricPayload,
      tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
      extra
    };
  }, [name, description, source, startTs, endTs, trigger, tags, metrics, catalog.data, extraText, copySource.data]);

  async function save() {
    if (tagError) {
      setError(tagError);
      return;
    }
    if (!metrics.length) {
      setError("请至少选择一个 Metric");
      return;
    }
    let metricPayload: unknown[];
    try {
      metricPayload = metrics.map((metric) =>
        scenarioMetricFromEditable(metric, catalog.data?.defs || [])
      );
    } catch {
      setError("Metric config JSON 格式错误");
      return;
    }
    let extra: unknown;
    try {
      extra = JSON.parse(extraText || "{}");
    } catch {
      setError("extra JSON 格式错误");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await api.scenarios.create({ ...payload, metrics: metricPayload, extra });
      navigate(`/scenarios/${created.id || created.scenario_id}/edit`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page">
      <PageHeader
        title={copyId ? "复制场景" : "场景创建"}
        subtitle={copyId ? `基于 ${copySource.data?.name || copyId} 预填，保存后才会创建新场景` : "录包片段 → 触发区间 → Metric 规则 → 标签 → 保存发布"}
        actions={<button type="button" className="btn ghost" onClick={() => navigate("/scenarios")}>取消</button>}
      />
      <DataState
        loading={catalog.loading || copySource.loading}
        error={catalog.error || copySource.error}
        empty={false}
        onRetry={catalog.reload}
      >
        <div className="grid two">
          <Card>
            <h2>基础信息</h2>
            <TextField label="场景名称" value={name} onChange={setName} />
            <TextField label="描述" value={description} onChange={setDescription} />
            <SourceEditor sources={catalog.data?.sources || []} draft={source} onChange={setSource} />
            <div className="row">
              <TextField label="start_ts" value={startTs} onChange={setStartTs} type="number" />
              <TextField label="end_ts" value={endTs} onChange={setEndTs} type="number" />
              <TextField label="trigger_ts" value={trigger} onChange={setTrigger} type="number" />
            </div>
            <TextField label="标签（逗号分隔）" value={tags} onChange={setTags} />
            <label className="field">
              <span>额外信息 extra（JSON）</span>
              <textarea rows={3} value={extraText} onChange={(event) => setExtraText(event.target.value)} />
            </label>
            {tagError && <div className="inline-error">{tagError}</div>}
            <p className="muted">{TAG_RULE_TEXT}</p>
          </Card>
          <Card>
            <h2>Metric 规则</h2>
            <p className="muted">选择 Metric 定义后可编辑完整 config（trigger_functions / trigger_ops / functions），保存时一次性形成 Scenario。</p>
            <MetricConfigEditor
              metrics={metrics}
              definitions={catalog.data?.defs || []}
              templates={catalog.data?.templates || []}
              onChange={setMetrics}
            />
            <h2>JSON 预览</h2>
            <pre className="json">{JSON.stringify(payload, null, 2)}</pre>
          </Card>
        </div>
        {error && <div className="inline-error">{error}</div>}
        <div className="actions">
          <button className="btn" onClick={save} disabled={saving || metrics.length === 0 || Boolean(tagError)}>
            {saving ? "保存中…" : "保存并发布 v1"}
          </button>
        </div>
      </DataState>
    </div>
  );
}
