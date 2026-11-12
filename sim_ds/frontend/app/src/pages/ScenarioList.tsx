import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useCursorList } from "../hooks";
import { Card, DataState, PageHeader, StatusBadge, formatTime } from "../components/ui";
import { VirtualList } from "../components/VirtualList";
import type { Scenario } from "../types";

export function ScenarioList() {
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const [status, setStatus] = useState("active");
  const list = useCursorList<Scenario>(
    (cursor) => api.scenarios.list({ search, tag, status, cursor, size: 50 }),
    [search, tag, status]
  );

  return (
    <div className="page">
      <PageHeader
        title="场景列表"
        subtitle="文件为事实源，列表读取 DB 投影；游标分页，禁止深翻页"
        actions={<Link className="btn" to="/scenarios/new">新建场景</Link>}
      />
      <Card className="filters">
        <input placeholder="搜索名称或 ID" value={search} onChange={(event) => setSearch(event.target.value)} />
        <input placeholder="标签，例如 cut-in" value={tag} onChange={(event) => setTag(event.target.value)} />
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="active">启用</option>
          <option value="archived">已归档</option>
          <option value="all">全部</option>
        </select>
        <button className="btn ghost" onClick={list.reload}>刷新</button>
        <span className="muted">已加载 {list.items.length} 条</span>
      </Card>
      <Card>
        <DataState loading={list.loading} error={list.error} empty={!list.loading && list.items.length === 0} onRetry={list.reload}>
          <VirtualList
            items={list.items}
            rowHeight={84}
            onEnd={list.loadMore}
            keyOf={(item) => item.id}
            render={(item) => (
              <div className="scenario-row">
                <div>
                  <strong>{item.name}</strong>
                  <small>{item.id} · v{item.version} · {formatTime(item.created_at)}</small>
                </div>
                <div className="tags">
                  {item.tags.slice(0, 4).map((tagName) => <span key={tagName}>{tagName}</span>)}
                </div>
                <StatusBadge status={item.status} />
                <Link className="link" to={`/scenarios/${item.id}/edit`}>编辑</Link>
              </div>
            )}
          />
          {list.next && (
            <button className="btn ghost more" onClick={list.loadMore} disabled={list.loadingMore}>
              {list.loadingMore ? "加载中…" : "加载更多"}
            </button>
          )}
        </DataState>
      </Card>
    </div>
  );
}
