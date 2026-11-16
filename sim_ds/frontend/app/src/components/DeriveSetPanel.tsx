import { useState } from "react";
import { api } from "../api";
import type { SetSummary } from "../types";
import { Card } from "./ui";

export function DeriveSetPanel({
  source,
  onDone,
  onCancel
}: {
  source: SetSummary;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(`${source.name}-派生`);
  const [visibility, setVisibility] = useState<"private" | "public">(source.visibility);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function confirm() {
    if (!name.trim()) {
      setError("请填写派生场景集名称");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.sets.derive(source.id, { name: name.trim(), visibility });
      onDone();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "派生失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h2>派生场景集</h2>
      <p className="muted">来源：{source.name} · v{source.current_version}</p>
      <label className="field">
        <span>新场景集名称</span>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="请输入派生场景集名称"
        />
      </label>
      <label className="field">
        <span>可见性</span>
        <select value={visibility} onChange={(event) => setVisibility(event.target.value as "private" | "public")}>
          <option value="private">私有</option>
          <option value="public">公共</option>
        </select>
      </label>
      {error && <div className="inline-error">{error}</div>}
      <div className="actions">
        <button className="btn" onClick={confirm} disabled={busy}>{busy ? "派生中…" : "确认派生"}</button>
        <button className="btn ghost" onClick={onCancel}>取消</button>
      </div>
    </Card>
  );
}
