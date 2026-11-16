import { useState } from "react";
import type { MetricDef, MetricInstance, MetricTemplate } from "../types";
import { buildMetricConfig } from "../metricConfig";

export interface EditableMetric extends MetricInstance {
  configText: string;
}

interface Props {
  metrics: EditableMetric[];
  definitions: MetricDef[];
  templates: MetricTemplate[];
  onChange: (metrics: EditableMetric[]) => void;
}

export function toEditable(metric: MetricInstance): EditableMetric {
  return { ...metric, configText: JSON.stringify(metric.config, null, 2) };
}

export function MetricConfigEditor({ metrics, definitions, templates, onChange }: Props) {
  const [definitionId, setDefinitionId] = useState("");

  function update(index: number, patch: Partial<EditableMetric>) {
    onChange(metrics.map((item, position) => (position === index ? { ...item, ...patch } : item)));
  }

  function add() {
    const definition = definitions.find((item) => `${item.id}@${item.version}` === definitionId);
    if (!definition) return;
    const config = buildMetricConfig(definition, templates);
    onChange([
      ...metrics,
      {
        metric_def_id: definition.id,
        metric_def_ver: definition.version,
        alias: null,
        enabled: true,
        config,
        configText: JSON.stringify(config, null, 2)
      }
    ]);
    setDefinitionId("");
  }

  return (
    <div className="metric-editor">
      {metrics.map((metric, index) => {
        let invalid = "";
        try {
          JSON.parse(metric.configText);
        } catch {
          invalid = "config JSON 格式错误";
        }
        return (
          <div className="metric-editor-item" key={`${metric.metric_def_id}-${index}`}>
            <div className="metric-editor-head">
              <code>{metric.metric_def_id}@v{metric.metric_def_ver}</code>
              <input
                placeholder="alias（同 def 多组时必填）"
                value={metric.alias || ""}
                onChange={(event) => update(index, { alias: event.target.value || null })}
              />
              <label className="check-row inline">
                <input
                  type="checkbox"
                  checked={metric.enabled}
                  onChange={(event) => update(index, { enabled: event.target.checked })}
                />
                <span>启用</span>
              </label>
              <button
                className="btn tiny danger"
                onClick={() => onChange(metrics.filter((_, position) => position !== index))}
              >
                移除
              </button>
            </div>
            <label className="field">
              <span>Metric config（trigger env / functions env 等完整规则实例）</span>
              <textarea
                rows={10}
                value={metric.configText}
                onChange={(event) => update(index, { configText: event.target.value })}
              />
            </label>
            {invalid && <div className="inline-error">{invalid}</div>}
          </div>
        );
      })}

      <div className="metric-add-row">
        <select value={definitionId} onChange={(event) => setDefinitionId(event.target.value)}>
          <option value="">选择 Metric 定义</option>
          {definitions.map((definition) => (
            <option key={`${definition.id}@${definition.version}`} value={`${definition.id}@${definition.version}`}>
              {definition.name} · {definition.id}@v{definition.version}
            </option>
          ))}
        </select>
        <button className="btn tiny ghost" onClick={add} disabled={!definitionId}>添加 Metric</button>
      </div>
    </div>
  );
}
