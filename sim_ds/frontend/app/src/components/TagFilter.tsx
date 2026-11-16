import { useState } from "react";
import { api } from "../api";
import { useAsync } from "../hooks";

export function TagFilter({
  value,
  onChange
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const tags = useAsync(() => api.tags.list({ search, size: 100 }), [search]);

  function appendTag(name: string) {
    const current = value.trim();
    if (!current) {
      onChange(name);
      return;
    }
    const separator = /[&|(]$/.test(current) ? " " : " & ";
    onChange(`${current}${separator}${name}`);
  }

  function appendOperator(operator: "&" | "|") {
    if (!value.trim()) return;
    onChange(`${value.trim()} ${operator} `);
  }

  return (
    <div className="tag-filter">
      <div className="tag-filter-row">
        <input
          className="tag-expression"
          placeholder="标签表达式，例如 A&B|C"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <button className="btn tiny ghost" onClick={() => setOpen((current) => !current)}>
          选择标签
        </button>
        <button className="btn tiny ghost" onClick={() => appendOperator("&")} disabled={!value.trim()}>AND</button>
        <button className="btn tiny ghost" onClick={() => appendOperator("|")} disabled={!value.trim()}>OR</button>
        <button className="btn tiny ghost" onClick={() => onChange("")} disabled={!value}>清空</button>
      </div>
      {open && (
        <div className="tag-dropdown">
          <input
            autoFocus
            placeholder="搜索已有标签"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <div className="tag-options">
            {tags.loading && <span className="muted">加载中…</span>}
            {tags.error && <span className="inline-error">{tags.error}</span>}
            {!tags.loading && !tags.error && (tags.data?.items.length || 0) === 0 && (
              <span className="muted">没有匹配标签</span>
            )}
            {tags.data?.items.map((tag) => (
              <button
                type="button"
                className="tag-option"
                key={tag.id}
                onClick={() => {
                  appendTag(tag.name);
                  setSearch("");
                }}
              >
                <span>{tag.name}</span>
                <small>{tag.usage} 个场景</small>
              </button>
            ))}
          </div>
          <small className="tag-help">
            点击标签追加；& 表示与，| 表示或；& 优先于 |，支持括号
          </small>
        </div>
      )}
    </div>
  );
}
