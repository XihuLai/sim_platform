import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAsync, useInterval } from "../hooks";
import { PlayerPanel } from "../components/PlayerPanel";
import { Card, DataState, PageHeader, StatusBadge, formatTime } from "../components/ui";
import type { DataSource } from "../types";

export function PlaybackPage() {
  const [params] = useSearchParams();
  const sources = useAsync(() => api.playback.list({ size: 100 }), []);
  const [sourceId, setSourceId] = useState("");
  const [compareId, setCompareId] = useState("");
  const [channel, setChannel] = useState("");
  const [compareChannel, setCompareChannel] = useState("");
  const [ts, setTs] = useState(0);
  const [compare, setCompare] = useState(false);
  const [indexing, setIndexing] = useState(false);

  const primary = useMemo<DataSource | undefined>(
    () => sources.data?.items.find((item) => item.source_id === sourceId),
    [sources.data, sourceId]
  );
  const secondary = useMemo<DataSource | undefined>(
    () => sources.data?.items.find((item) => item.source_id === compareId),
    [sources.data, compareId]
  );
  const primaryChannels = useAsync(() => api.playback.channels(sourceId), [sourceId]);
  const secondaryChannels = useAsync(() => api.playback.channels(compareId), [compareId]);

  useEffect(() => {
    if (!sourceId && sources.data?.items.length) setSourceId(sources.data.items[0].source_id);
  }, [sources.data, sourceId]);

  useEffect(() => {
    const rows = (primaryChannels.data?.channels as Array<{ name: string }>) || [];
    if (rows.length && !rows.some((item) => item.name === channel)) setChannel(rows[0].name);
  }, [primaryChannels.data, channel]);

  useEffect(() => {
    const rows = (secondaryChannels.data?.channels as Array<{ name: string }>) || [];
    if (rows.length && !rows.some((item) => item.name === compareChannel)) setCompareChannel(rows[0].name);
  }, [secondaryChannels.data, compareChannel]);

  useInterval(() => {
    sources.reload();
    if (sourceId) primaryChannels.reload();
    if (compareId) secondaryChannels.reload();
  }, indexing ? 2000 : null);

  useEffect(() => {
    const status = primary?.status;
    setIndexing(status === "indexing" || status === "pending");
  }, [primary?.status]);

  async function ensureIndex() {
    if (!sourceId) return;
    await api.playback.index(sourceId);
    setIndexing(true);
    sources.reload();
  }

  const duration = primary?.duration_ms || 180000;
  const channels = (primaryChannels.data?.channels as Array<{ name: string; type: string; fps: number }>) || [];
  const compareChannels = (secondaryChannels.data?.channels as Array<{ name: string }>) || [];

  return (
    <div className="page">
      <PageHeader
        title="数据播放"
        subtitle={params.get("case") ? `来自 Case ${params.get("case")} 的播放入口` : "单路 / 对比播放，时间轴按需加载 chunk 与 frame"}
      />
      <DataState loading={sources.loading} error={sources.error} empty={!sources.data?.items.length} onRetry={sources.reload}>
        <Card className="filters">
          <label className="field inline">
            <span>主数据源</span>
            <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
              {sources.data?.items.map((item) => (
                <option key={item.source_id} value={item.source_id}>
                  {item.source_id} · {item.kind} · {item.status}
                </option>
              ))}
            </select>
          </label>
          <label className="check-row inline">
            <input type="checkbox" checked={compare} onChange={(event) => setCompare(event.target.checked)} />
            <span>对比原始/仿真</span>
          </label>
          {compare && (
            <label className="field inline">
              <span>对比数据源</span>
              <select value={compareId} onChange={(event) => setCompareId(event.target.value)}>
                <option value="">请选择</option>
                {sources.data?.items.filter((item) => item.source_id !== sourceId).map((item) => (
                  <option key={item.source_id} value={item.source_id}>{item.source_id} · {item.kind}</option>
                ))}
              </select>
            </label>
          )}
          {primary && <StatusBadge status={primary.status} />}
          {primary && primary.status !== "ready" && (
            <button className="btn tiny" onClick={ensureIndex} disabled={primary.status === "indexing"}>
              {primary.status === "indexing" ? `索引中 ${primary.progress}%` : "异步建索引"}
            </button>
          )}
        </Card>

        <Card className="timeline-card">
          <div className="timeline-head">
            <strong>{ts} ms / {duration} ms</strong>
            <span className="muted">seek 目标 &lt; 500ms · 当前数据源 {primary?.source_id || "—"}</span>
          </div>
          <input
            className="timeline"
            type="range"
            min={0}
            max={duration}
            step={100}
            value={Math.min(ts, duration)}
            onChange={(event) => setTs(Number(event.target.value))}
          />
          <div className="row-actions">
            <button className="btn tiny ghost" onClick={() => setTs((value) => Math.max(0, value - 5000))}>-5s</button>
            <button className="btn tiny ghost" onClick={() => setTs((value) => Math.max(0, value - 1000))}>-1s</button>
            <button className="btn tiny ghost" onClick={() => setTs((value) => Math.min(duration, value + 1000))}>+1s</button>
            <button className="btn tiny ghost" onClick={() => setTs((value) => Math.min(duration, value + 5000))}>+5s</button>
            <span className="muted">通道：</span>
            {channels.map((item) => (
              <button key={item.name} className={`pill ${channel === item.name ? "active" : ""}`} onClick={() => setChannel(item.name)}>
                {item.name} · {item.type}
              </button>
            ))}
          </div>
        </Card>

        <div className={compare ? "grid two" : ""}>
          <PlayerPanel
            title={`${primary?.kind || "source"} · ${primary?.source_id || ""}`}
            sourceId={sourceId}
            channel={channel}
            ts={ts}
            onSeekTime={setTs}
          />
          {compare && (
            <PlayerPanel
              title={`${secondary?.kind || "source"} · ${secondary?.source_id || "未选择"}`}
              sourceId={compareId}
              channel={compareChannel}
              ts={ts}
              onSeekTime={setTs}
            />
          )}
        </div>
        {compare && compareChannels.length > 1 && (
          <Card className="filters">
            <span className="muted">对比通道：</span>
            {compareChannels.map((item) => (
              <button key={item.name} className={`pill ${compareChannel === item.name ? "active" : ""}`} onClick={() => setCompareChannel(item.name)}>
                {item.name}
              </button>
            ))}
          </Card>
        )}
        <Card>
          <h2>数据源索引状态</h2>
          <div className="source-grid">
            {sources.data?.items.map((item) => (
              <div key={item.source_id} className="source-card">
                <strong>{item.source_id}</strong>
                <StatusBadge status={item.status} />
                <small>{item.kind} · {item.channels.length} 通道 · {formatTime(item.created_at)}</small>
                {item.error && <em>{item.error}</em>}
              </div>
            ))}
          </div>
        </Card>
      </DataState>
    </div>
  );
}
