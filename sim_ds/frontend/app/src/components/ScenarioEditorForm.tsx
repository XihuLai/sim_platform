import { TAG_RULE_TEXT } from "../tags";
import type { ScenarioSource } from "../types";
import { Card, TextField } from "./ui";

export interface ScenarioFormState {
  name: string;
  description: string;
  tags: string;
  source: ScenarioSource;
  timeWindow: { start_ts: string; end_ts: string; trigger_ts: string };
}

const FORMATS = ["rsclbag", "mcap", "bag", "parquet"];

const EMPTY_SOURCE: ScenarioSource = {
  type: "record",
  log_id: "",
  log_uri: "",
  log_checksum: "",
  format: "rsclbag"
};

export function initialScenarioForm(): ScenarioFormState {
  return {
    name: "",
    description: "",
    tags: "",
    source: EMPTY_SOURCE,
    timeWindow: { start_ts: "0", end_ts: "180000", trigger_ts: "0" }
  };
}

export function ScenarioEditorForm({
  form,
  onChange
}: {
  form: ScenarioFormState;
  onChange: (form: ScenarioFormState) => void;
}) {
  const set = (patch: Partial<ScenarioFormState>) => onChange({ ...form, ...patch });
  const setSource = (patch: Partial<ScenarioSource>) =>
    onChange({ ...form, source: { ...form.source, ...patch } });
  const windowValid =
    Number(form.timeWindow.start_ts) <= Number(form.timeWindow.trigger_ts) &&
    Number(form.timeWindow.trigger_ts) <= Number(form.timeWindow.end_ts);

  return (
    <>
      <Card>
        <h2>基础信息</h2>
        <TextField label="场景名称" value={form.name} onChange={(value) => set({ name: value })} />
        <TextField label="描述" value={form.description} onChange={(value) => set({ description: value })} />
        <TextField label="标签（逗号分隔）" value={form.tags} onChange={(value) => set({ tags: value })} />
        <p className="muted">{TAG_RULE_TEXT}</p>
      </Card>

      <Card>
        <h2>数据源</h2>
        <div className="row">
          <label className="field">
            <span>类型</span>
            <select value={form.source.type} onChange={(event) => setSource({ type: event.target.value })}>
              <option value="record">record</option>
              <option value="synthetic">synthetic</option>
            </select>
          </label>
          <label className="field">
            <span>格式</span>
            <select value={form.source.format} onChange={(event) => setSource({ format: event.target.value })}>
              {FORMATS.map((format) => <option key={format} value={format}>{format}</option>)}
            </select>
          </label>
        </div>
        <TextField label="Log ID" value={form.source.log_id} onChange={(value) => setSource({ log_id: value })} />
        <TextField label="Log URI" value={form.source.log_uri} onChange={(value) => setSource({ log_uri: value })} />
        <TextField
          label="Log 校验和"
          value={form.source.log_checksum}
          onChange={(value) => setSource({ log_checksum: value })}
        />
      </Card>

      <Card>
        <h2>时间窗与触发点</h2>
        <div className="row">
          <TextField
            label="start_ts"
            type="number"
            value={form.timeWindow.start_ts}
            onChange={(value) => set({ timeWindow: { ...form.timeWindow, start_ts: value } })}
          />
          <TextField
            label="trigger_ts（常用修改项）"
            type="number"
            value={form.timeWindow.trigger_ts}
            onChange={(value) => set({ timeWindow: { ...form.timeWindow, trigger_ts: value } })}
          />
          <TextField
            label="end_ts"
            type="number"
            value={form.timeWindow.end_ts}
            onChange={(value) => set({ timeWindow: { ...form.timeWindow, end_ts: value } })}
          />
        </div>
        {!windowValid && <div className="inline-error">必须满足 start_ts ≤ trigger_ts ≤ end_ts</div>}
      </Card>
    </>
  );
}
