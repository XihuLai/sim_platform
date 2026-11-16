import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`card ${className}`}>{children}</section>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}

export function Empty({ title = "暂无数据", hint }: { title?: string; hint?: string }) {
  return (
    <div className="state empty">
      <strong>{title}</strong>
      {hint && <span>{hint}</span>}
    </div>
  );
}

export function Loading({ text = "正在加载" }: { text?: string }) {
  return (
    <div className="state loading">
      <span className="spinner" />
      {text}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state error">
      <strong>加载失败</strong>
      <span>{message}</span>
      {onRetry && (
        <button className="btn ghost" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}

export function DataState({
  loading,
  error,
  empty,
  onRetry,
  children
}: {
  loading: boolean;
  error: string | null;
  empty: boolean;
  onRetry?: () => void;
  children: ReactNode;
}) {
  if (loading) return <Loading />;
  if (error) return <ErrorState message={error} onRetry={onRetry} />;
  if (empty) return <Empty />;
  return <>{children}</>;
}

const STATUS_TEXT: Record<string, string> = {
  queued: "排队中",
  scheduled: "已调度",
  running: "运行中",
  paused: "已暂停",
  expanding: "展开中",
  succeeded: "成功",
  failed: "失败",
  canceled: "已取消",
  timeout: "超时",
  worker_lost: "失联",
  ready: "就绪",
  indexing: "索引中",
  pending: "待处理",
  active: "启用",
  archived: "已归档",
  unavailable: "不可用",
  draft: "未冻结",
  frozen: "已冻结",
  public: "公共",
  private: "私有"
};

export function statusLabel(status: string): string {
  return STATUS_TEXT[status] || status;
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge status-${status}`}>{statusLabel(status)}</span>;
}

export function ResultBadge({
  status,
  metrics
}: {
  status: string;
  metrics?: Record<string, { pass?: boolean | null }>;
}) {
  const hasFailedMetric = Object.values(metrics || {}).some((item) => item.pass === false);
  if (status === "succeeded" && hasFailedMetric) {
    return <span className="badge status-failed">指标未通过</span>;
  }
  return <StatusBadge status={status} />;
}

export function PriorityBadge({ priority }: { priority: number }) {
  const color = priority <= 2 ? "high" : priority <= 5 ? "mid" : "low";
  return <span className={`badge priority-${color}`}>P{priority}</span>;
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="progress" aria-label={`进度 ${value}%`}>
      <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      <em>{value.toFixed(0)}%</em>
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  options,
  onChange
}: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
}) {
  return (
    <div className="tabs">
      {options.map((option) => (
        <button
          key={option.value}
          className={option.value === value ? "active" : ""}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  type = "text"
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

export function formatTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}
