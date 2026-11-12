import { useEffect, useState } from "react";
import { api } from "../api";
import type { ChunkPayload } from "../types";

interface Props {
  title: string;
  sourceId: string;
  channel: string;
  ts: number;
  onSeekTime: (ms: number) => void;
}

export function PlayerPanel({ title, sourceId, channel, ts, onSeekTime }: Props) {
  const [chunk, setChunk] = useState<ChunkPayload | null>(null);
  const [frame, setFrame] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seekMs, setSeekMs] = useState<number | null>(null);

  useEffect(() => {
    if (!sourceId || !channel) return;
    let alive = true;
    const started = performance.now();
    setLoading(true);
    setError(null);
    Promise.all([
      api.playback.chunk(sourceId, channel, ts, 2000),
      api.playback.frame(sourceId, channel, ts)
    ])
      .then(([chunkData, frameData]) => {
        if (!alive) return;
        setChunk(chunkData);
        setFrame(frameData);
        setSeekMs(performance.now() - started);
      })
      .catch((reason: unknown) => {
        if (alive) setError(reason instanceof Error ? reason.message : "加载失败");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [sourceId, channel, ts]);

  return (
    <div className="player-panel">
      <div className="player-head">
        <strong>{title}</strong>
        <span className={`seek ${seekMs !== null && seekMs < 500 ? "ok" : "warn"}`}>
          {loading ? "加载中…" : seekMs !== null ? `${seekMs.toFixed(0)} ms` : "—"}
        </span>
      </div>
      {error && <div className="inline-error">{error}</div>}
      <div className="viewport">
        {chunk?.type === "video" && typeof frame?.svg === "string" ? (
          <div dangerouslySetInnerHTML={{ __html: frame.svg }} />
        ) : chunk?.type === "pointcloud" ? (
          <PointCloud points={(frame?.points as Array<{ x: number; y: number }>) || []} />
        ) : (
          <TimeSeries samples={chunk?.samples || []} onSeekTime={onSeekTime} />
        )}
      </div>
      <div className="player-foot">
        <span>{channel || "未选择通道"}</span>
        <span>{chunk?.type || "—"} · {chunk?.fps || 0} fps</span>
        <span>{ts} ms</span>
      </div>
    </div>
  );
}

function PointCloud({ points }: { points: Array<{ x: number; y: number }> }) {
  if (!points.length) return <div className="player-empty">当前时间点无点云</div>;
  const scale = 7;
  return (
    <svg viewBox="0 0 480 260" className="pointcloud">
      <rect width="480" height="260" fill="#151c24" />
      <line x1="240" y1="0" x2="240" y2="260" stroke="#2d3a47" />
      <line x1="0" y1="130" x2="480" y2="130" stroke="#2d3a47" />
      {points.map((point, index) => (
        <circle key={index} cx={240 + point.x * scale} cy={130 - point.y * scale} r={1.6} fill="#67e8f9" />
      ))}
    </svg>
  );
}

function TimeSeries({
  samples,
  onSeekTime
}: {
  samples: Array<Record<string, number>>;
  onSeekTime: (ms: number) => void;
}) {
  if (!samples.length) return <div className="player-empty">当前时间窗无时序样本</div>;
  const values = samples.map((item) => Number(item.value ?? 0));
  const times = samples.map((item) => Number(item.ts ?? 0));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((value, index) => `${(index / Math.max(1, values.length - 1)) * 460 + 10},${120 - ((value - min) / span) * 90}`)
    .join(" ");
  return (
    <svg viewBox="0 0 480 260" className="timeseries">
      <rect width="480" height="260" fill="#101820" />
      <polyline points={points} fill="none" stroke="#34d399" strokeWidth="2" />
      <line x1="10" y1="210" x2="470" y2="210" stroke="#2d3a47" />
      <text x="14" y="228" fill="#8fa3b8" fontSize="12">{times[0]} ms</text>
      <text x="400" y="228" fill="#8fa3b8" fontSize="12">{times[times.length - 1]} ms</text>
      <text x="14" y="24" fill="#8fa3b8" fontSize="12">value {values[0].toFixed(2)}</text>
      <rect
        x="10" y="238" width="460" height="14" fill="#22303c" rx="4"
        onClick={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const ratio = (event.clientX - rect.left) / rect.width;
          onSeekTime(Math.round(times[0] + ratio * (times[times.length - 1] - times[0])));
        }}
      />
    </svg>
  );
}
