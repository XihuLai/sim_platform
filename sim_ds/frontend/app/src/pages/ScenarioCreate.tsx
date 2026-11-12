import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { Card, DataState, PageHeader, TextField } from "../components/ui";
import type { MetricDef, MetricTemplate } from "../types";

function configFor(definition: MetricDef, templates: MetricTemplate[]) {
  const build = (refs: Array<{ template_id: string }>) =>
    refs.map((ref) => {
      const template = templates.find((item) => item.id === ref.template_id);
      return {
        name: template?.name || ref.template_id,
        function_field_name: template?.name || "",
        template_id: ref.template_id,
        env: structuredClone(template?.env_example || {})
      };
    });
  return {
    trigger_functions: build(definition.trigger_templates),
    trigger_ops: ["AND"],
    functions: build(definition.function_templates),
    ops: [],
    ret: "pass",
    action: "not_stop_sim",
    level: definition.level || "S0",
    is_global: false
  };
}

export function ScenarioCreate() {
  const navigate = useNavigate();
  const catalog = useAsync(async () => {
    const [types, defs, templates, sources] = await Promise.all([
      api.metrics.types(),
      api.metrics.defs(),
      api.metrics.templates(),
      api.playback.list({ size: 50 })
    ]);
    return { types: types.items, defs: defs.items, templates: templates.items, sources: sources.items };
  }, []);

  const [name, setName] = useState("城市路口-新场景");
  const [description, setDescription] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [logId, setLogId] = useState("log-001");
  const [clipStart, setClipStart] = useState("0");
  const [clipEnd, setClipEnd] = useState("180000");
  const [trigger, setTrigger] = useState("60000");
  const [tags, setTags] = useState("cut-in, junction");
  const [defId, setDefId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!defId && catalog.data?.defs.length) setDefId(catalog.data.defs[0].id);
  }, [catalog.data, defId]);

  const selectedSource = catalog.data?.sources.find((item) => item.source_id === sourceId);
  const payload = useMemo(() => {
    const definition = catalog.data?.defs.find((item) => item.id === defId);
    const metric = definition
      ? [{
          metric_def_id: definition.id,
          metric_def_ver: definition.version,
          alias: null,
          config: configFor(definition, catalog.data?.templates || []),
          enabled: true,
          extra: {}
        }]
      : [];
    return {
      name,
      description,
      project: localStorage.getItem("sim.project") || "default",
      source: {
        type: "record",
        log_id: selectedSource?.source_id || logId,
        log_uri: selectedSource?.uri || "",
        log_checksum: "sha256:demo",
        format: "mcap",
        extract: { clip_start_ts: Number(clipStart), clip_end_ts: Number(clipEnd) },
        channels: selectedSource?.channels.map((channel) => channel.name) || ["camera_front", "can"]
      },
      time_window: { start_ts: Number(clipStart), end_ts: Number(clipEnd), trigger_ts: Number(trigger) },
      metrics: metric,
      tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
      extra: {}
    };
  }, [name, description, sourceId, logId, clipStart, clipEnd, trigger, tags, defId, catalog.data, selectedSource]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const created = await api.scenarios.create(payload);
      navigate(`/scenarios/${created.id}/edit`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page">
      <PageHeader title="场景创建" subtitle="录包片段 → 触发区间 → Metric 规则 → 标签 → 保存发布" />
      <DataState loading={catalog.loading} error={catalog.error} empty={false} onRetry={catalog.reload}>
        <div className="grid two">
          <Card>
            <h2>基础信息</h2>
            <TextField label="场景名称" value={name} onChange={setName} />
            <TextField label="描述" value={description} onChange={setDescription} />
            <label className="field">
              <span>数据源（可留空手填 log）</span>
              <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
                <option value="">手动填写</option>
                {catalog.data?.sources.map((source) => (
                  <option key={source.source_id} value={source.source_id}>
                    {source.source_id} · {source.kind} · {source.duration_ms}ms
                  </option>
                ))}
              </select>
            </label>
            <TextField label="Log ID" value={logId} onChange={setLogId} />
            <div className="row">
              <TextField label="片段开始 ms" value={clipStart} onChange={setClipStart} type="number" />
              <TextField label="片段结束 ms" value={clipEnd} onChange={setClipEnd} type="number" />
              <TextField label="触发点 ms" value={trigger} onChange={setTrigger} type="number" />
            </div>
            <TextField label="标签（逗号分隔）" value={tags} onChange={setTags} />
          </Card>
          <Card>
            <h2>Metric 规则</h2>
            <label className="field">
              <span>Metric 定义（category → type 分组）</span>
              <select value={defId} onChange={(event) => setDefId(event.target.value)}>
                {catalog.data?.types.map((type) => {
                  const defs = catalog.data?.defs.filter((item) => item.type_id === type.id) || [];
                  if (!defs.length) return null;
                  return (
                    <optgroup key={type.id} label={`${type.category_id} / ${type.name}`}>
                      {defs.map((definition) => (
                        <option key={definition.id} value={definition.id}>
                          {definition.name} · {definition.id}@v{definition.version}
                        </option>
                      ))}
                    </optgroup>
                  );
                })}
              </select>
            </label>
            <p className="muted">模板 env 默认值来自 metric_template.env_example，保存前由后端执行结构 + 动态 Schema 两级校验。</p>
            <h2>JSON 预览</h2>
            <pre className="json">{JSON.stringify(payload, null, 2)}</pre>
          </Card>
        </div>
        {error && <div className="inline-error">{error}</div>}
        <div className="actions">
          <button className="btn" onClick={save} disabled={saving || !defId}>
            {saving ? "保存中…" : "保存并发布 v1"}
          </button>
        </div>
      </DataState>
    </div>
  );
}
