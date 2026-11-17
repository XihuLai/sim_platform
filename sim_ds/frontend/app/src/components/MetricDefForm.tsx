import { useState } from "react";
import { api } from "../api";
import type { MetricDef, MetricType } from "../types";
import { Card, TextField } from "./ui";

function parseArray(text: string, label: string): unknown[] {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(`${label} 不是合法 JSON`);
  }
  if (!Array.isArray(value)) throw new Error(`${label} 必须是 JSON 数组`);
  return value;
}

export function MetricDefForm({
  types,
  initial,
  onCreated,
  onCancel
}: {
  types: MetricType[];
  initial?: MetricDef;
  onCreated: (id: string) => void;
  onCancel: () => void;
}) {
  const [id, setId] = useState(initial?.id || "");
  const [version, setVersion] = useState(String(initial?.version || 1));
  const [typeId, setTypeId] = useState(initial?.type_id || types[0]?.id || "");
  const [name, setName] = useState(initial?.name || "");
  const [level, setLevel] = useState(initial?.level || "S0");
  const [businessType, setBusinessType] = useState(initial?.business_type || "dpc");
  const [runMode, setRunMode] = useState<"async" | "sync">(initial?.run_mode || "async");
  const [description, setDescription] = useState(initial?.description || "");
  const [ret, setRet] = useState<"pass" | "fail">(initial?.ret || "pass");
  const [action, setAction] = useState(initial?.action || "not_stop_sim");
  const [triggerFunctions, setTriggerFunctions] = useState(JSON.stringify(initial?.trigger_functions || [], null, 2));
  const [triggerOps, setTriggerOps] = useState(JSON.stringify(initial?.trigger_ops || ["AND"], null, 2));
  const [functions, setFunctions] = useState(JSON.stringify(initial?.functions || [], null, 2));
  const [ops, setOps] = useState(JSON.stringify(initial?.ops || [], null, 2));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!name.trim() || !typeId) {
      setError("名称、类型不能为空");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = {
        id: initial?.id || id.trim(),
        version: initial?.version || Number(version) || 1,
        type_id: typeId,
        name: name.trim(),
        level,
        business_type: businessType,
        run_mode: runMode,
        is_global: false,
        trigger_functions: parseArray(triggerFunctions, "trigger_functions"),
        trigger_ops: parseArray(triggerOps, "trigger_ops"),
        functions: parseArray(functions, "functions"),
        ops: parseArray(ops, "ops"),
        ret,
        action,
        status: "active",
        description
      };
      const created = initial
        ? await api.metrics.updateDef(initial.id, body)
        : await api.metrics.createDef(body);
      onCreated(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="card-head">
        <h2>{initial ? "编辑 Metric 定义" : "新增 Metric 定义"}</h2>
        <button className="btn tiny ghost" onClick={onCancel}>取消</button>
      </div>
      <div className="grid two">
        <div>
          {initial ? (
            <TextField label="Metric ID" value={id} onChange={setId} />
          ) : (
            <p className="muted">
              Metric ID 按类型自动分配：舒适 1001+ / 合规 2001+ / 安全 3001+ / 效率 4001+ / 导航 5001+
            </p>
          )}
          <TextField label="名称" value={name} onChange={setName} />
          <div className="row">
            <TextField label={initial ? "当前版本（保存后 +1）" : "版本"} type="number" value={version} onChange={setVersion} />
            <label className="field">
              <span>类型</span>
              <select value={typeId} onChange={(event) => setTypeId(event.target.value)}>
                {types.map((type) => <option key={type.id} value={type.id}>{type.name} · {type.id}</option>)}
              </select>
            </label>
          </div>
          <div className="row">
            <label className="field">
              <span>level</span>
              <select value={level} onChange={(event) => setLevel(event.target.value)}>
                <option value="S0">S0</option><option value="S1">S1</option><option value="S2">S2</option>
              </select>
            </label>
            <label className="field">
              <span>run_mode</span>
              <select value={runMode} onChange={(event) => setRunMode(event.target.value as "async" | "sync")}>
                <option value="async">async</option><option value="sync">sync</option>
              </select>
            </label>
            <label className="field">
              <span>结果</span>
              <select value={ret} onChange={(event) => setRet(event.target.value as "pass" | "fail")}>
                <option value="pass">pass</option><option value="fail">fail</option>
              </select>
            </label>
          </div>
          <TextField label="business_type" value={businessType} onChange={setBusinessType} />
          <TextField label="action" value={action} onChange={setAction} />
          <TextField label="描述" value={description} onChange={setDescription} />
        </div>
        <div>
          <label className="field">
            <span>trigger_functions（JSON 数组）</span>
            <textarea rows={10} value={triggerFunctions} onChange={(event) => setTriggerFunctions(event.target.value)} />
          </label>
          <label className="field">
            <span>trigger_ops（JSON 数组，AND/OR）</span>
            <textarea rows={3} value={triggerOps} onChange={(event) => setTriggerOps(event.target.value)} />
          </label>
          <label className="field">
            <span>functions（JSON 数组）</span>
            <textarea rows={10} value={functions} onChange={(event) => setFunctions(event.target.value)} />
          </label>
          <label className="field">
            <span>ops（JSON 数组，可选）</span>
            <textarea rows={3} value={ops} onChange={(event) => setOps(event.target.value)} />
          </label>
        </div>
      </div>
      {error && <div className="inline-error">{error}</div>}
      <button className="btn" onClick={save} disabled={busy}>
        {busy ? "保存中…" : initial ? "保存新版本" : "创建 Metric"}
      </button>
    </Card>
  );
}
