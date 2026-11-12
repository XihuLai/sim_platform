import { useRef, useState, type ReactNode, type UIEvent } from "react";

interface Props<T> {
  items: T[];
  rowHeight: number;
  height?: number;
  render: (item: T, index: number) => ReactNode;
  onEnd?: () => void;
  keyOf: (item: T) => string;
}

export function VirtualList<T>({ items, rowHeight, height = 460, render, onEnd, keyOf }: Props<T>) {
  const [scroll, setScroll] = useState(0);
  const frame = useRef(0);
  const overscan = 4;
  const visible = Math.ceil(height / rowHeight) + overscan * 2;
  const start = Math.max(0, Math.floor(scroll / rowHeight) - overscan);
  const end = Math.min(items.length, start + visible);

  function handleScroll(event: UIEvent<HTMLDivElement>) {
    const top = event.currentTarget.scrollTop;
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      setScroll(top);
      if (onEnd && top + height >= items.length * rowHeight - rowHeight * 3) onEnd();
    });
  }

  return (
    <div className="virtual" style={{ height }} onScroll={handleScroll}>
      <div style={{ height: items.length * rowHeight, position: "relative" }}>
        {items.slice(start, end).map((item, offset) => (
          <div
            key={keyOf(item)}
            className="virtual-row"
            style={{ position: "absolute", top: (start + offset) * rowHeight, height: rowHeight }}
          >
            {render(item, start + offset)}
          </div>
        ))}
      </div>
      {items.length === 0 && <div className="virtual-empty">暂无数据</div>}
    </div>
  );
}
