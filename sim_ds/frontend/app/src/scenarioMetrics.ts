import type { EditableMetric } from "./components/MetricConfigEditor";
import type { MetricDef, ScenarioMetric } from "./types";

export function editableFromScenario(
  metric: ScenarioMetric,
  definitions: MetricDef[]
): EditableMetric {
  const definition = definitions.find((item) => item.id === metric.id);
  const config = {
    trigger_functions: metric.trigger_functions || [],
    trigger_ops: metric.trigger_ops || [],
    functions: metric.functions || [],
    ops: metric.ops || [],
    ret: metric.ret || "pass",
    action: metric.action || "not_stop_sim",
    level: metric.level || "S0",
    is_global: Boolean(metric.is_global)
  };
  return {
    metric_def_id: metric.id,
    metric_def_ver: definition?.version || 1,
    alias: null,
    enabled: true,
    config,
    configText: JSON.stringify(config, null, 2)
  };
}

export function scenarioMetricFromEditable(
  metric: EditableMetric,
  definitions: MetricDef[]
): ScenarioMetric {
  const config = JSON.parse(metric.configText) as Record<string, unknown>;
  const definition = definitions.find((item) => item.id === metric.metric_def_id);
  return {
    id: metric.metric_def_id,
    name: definition?.name || metric.metric_def_id,
    desc: definition?.description || "",
    business_type: definition?.business_type || "dpc",
    run_mode: definition?.run_mode || "async",
    level: String(config.level || definition?.level || "S0"),
    is_global: Boolean(config.is_global),
    trigger_functions: (config.trigger_functions || []) as ScenarioMetric["trigger_functions"],
    trigger_ops: (config.trigger_ops || []) as ScenarioMetric["trigger_ops"],
    functions: (config.functions || []) as ScenarioMetric["functions"],
    ops: (config.ops || []) as ScenarioMetric["ops"],
    ret: (config.ret || "pass") as ScenarioMetric["ret"],
    action: String(config.action || "not_stop_sim")
  };
}
