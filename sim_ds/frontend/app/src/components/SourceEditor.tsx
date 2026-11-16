import type { DataSource } from "../types";
import { TextField } from "./ui";

export interface SourceDraft {
  sourceId: string;
  logId: string;
  logUri: string;
  logChecksum: string;
  format: "rsclbag" | "mcap" | "bag" | "parquet";
}

const FORMATS: SourceDraft["format"][] = ["rsclbag", "mcap", "bag", "parquet"];

export function SourceEditor({
  sources,
  draft,
  onChange
}: {
  sources: DataSource[];
  draft: SourceDraft;
  onChange: (draft: SourceDraft) => void;
}) {
  function set<K extends keyof SourceDraft>(key: K, value: SourceDraft[K]) {
    onChange({ ...draft, [key]: value });
  }

  function choose(sourceId: string) {
    const source = sources.find((item) => item.source_id === sourceId);
    if (!source) {
      onChange({ ...draft, sourceId: "" });
      return;
    }
    onChange({
      ...draft,
      sourceId,
      logId: source.source_id,
      logUri: source.uri
    });
  }

  return (
    <>
      <label className="field">
        <span>已索引数据源（可选，选择后自动填充下方字段）</span>
        <select value={draft.sourceId} onChange={(event) => choose(event.target.value)}>
          <option value="">手动填写</option>
          {sources.map((source) => (
            <option key={source.source_id} value={source.source_id}>
              {source.source_id} · {source.kind} · {source.duration_ms}ms
            </option>
          ))}
        </select>
      </label>
      <TextField label="Log ID" value={draft.logId} onChange={(value) => set("logId", value)} />
      <TextField
        label="Log URI（rsclbag/mcap/bag/parquet 路径）"
        value={draft.logUri}
        onChange={(value) => set("logUri", value)}
        placeholder="sources/raw/log-01.rsclbag"
      />
      <div className="row">
        <TextField
          label="Log 校验和"
          value={draft.logChecksum}
          onChange={(value) => set("logChecksum", value)}
        />
        <label className="field">
          <span>格式</span>
          <select value={draft.format} onChange={(event) => set("format", event.target.value as SourceDraft["format"])}>
            {FORMATS.map((format) => <option key={format} value={format}>{format}</option>)}
          </select>
        </label>
      </div>
    </>
  );
}
