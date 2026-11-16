import type { MetricDef, MetricTemplate } from "./types";

export function buildMetricConfig(definition: MetricDef, templates: MetricTemplate[]) {
  if ((definition.trigger_functions?.length || 0) > 0 || (definition.functions?.length || 0) > 0) {
    return {
      trigger_functions: structuredClone(definition.trigger_functions || []),
      trigger_ops: definition.trigger_ops?.length ? [...definition.trigger_ops] : ["AND"],
      functions: structuredClone(definition.functions || []),
      ops: definition.ops?.length ? [...definition.ops] : [],
      ret: definition.ret || "pass",
      action: definition.action || "not_stop_sim",
      level: definition.level || "S0",
      is_global: false
    };
  }
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
