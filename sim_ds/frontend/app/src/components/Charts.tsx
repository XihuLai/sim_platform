const COLORS = ["#3b82f6", "#22c55e", "#ef4444", "#f59e0b", "#8b5cf6", "#06b6d4", "#64748b"];

export function Donut({
  items,
  centerLabel
}: {
  items: Array<{ key: string; value: number; label?: string }>;
  centerLabel?: string;
}) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="donut-wrap">
      <svg viewBox="0 0 160 160" className="donut" role="img" aria-label="状态占比">
        <circle cx="80" cy="80" r={radius} fill="none" stroke="#e8edf5" strokeWidth="20" />
        {total > 0 &&
          items.map((item, index) => {
            const length = (item.value / total) * circumference;
            const circle = (
              <circle
                key={item.key}
                cx="80"
                cy="80"
                r={radius}
                fill="none"
                stroke={COLORS[index % COLORS.length]}
                strokeWidth="20"
                strokeDasharray={`${length} ${circumference - length}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 80 80)"
              />
            );
            offset += length;
            return circle;
          })}
        <text x="80" y="76" textAnchor="middle" className="donut-value">
          {total}
        </text>
        <text x="80" y="96" textAnchor="middle" className="donut-label">
          {centerLabel || "总计"}
        </text>
      </svg>
      <ul className="legend">
        {items.map((item, index) => (
          <li key={item.key}>
            <i style={{ background: COLORS[index % COLORS.length] }} />
            <span>{item.label || item.key}</span>
            <b>{item.value}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BarChart({
  items,
  unit = ""
}: {
  items: Array<{ key: string; value: number; label?: string }>;
  unit?: string;
}) {
  const max = Math.max(1, ...items.map((item) => item.value));
  return (
    <div className="bars" role="img" aria-label="指标分布">
      {items.map((item) => (
        <div className="bar-row" key={item.key}>
          <span className="bar-label" title={item.label || item.key}>
            {item.label || item.key}
          </span>
          <div className="bar-track">
            <span style={{ width: `${(item.value / max) * 100}%` }} />
          </div>
          <b>
            {item.value}
            {unit}
          </b>
        </div>
      ))}
      {items.length === 0 && <div className="muted">暂无指标数据</div>}
    </div>
  );
}
