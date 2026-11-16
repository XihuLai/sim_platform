import type { CursorState } from "../hooks";
import type { SetSummary } from "../types";
import { Card, DataState, StatusBadge, Tabs, formatTime } from "./ui";
import { VirtualList } from "./VirtualList";

export function SetListPanel({
  sets,
  visibility,
  onVisibility,
  onMembers,
  onFreeze,
  onDerive
}: {
  sets: CursorState<SetSummary>;
  visibility: "public" | "private";
  onVisibility: (value: "public" | "private") => void;
  onMembers: (item: SetSummary) => void;
  onFreeze: (item: SetSummary) => void;
  onDerive: (item: SetSummary) => void;
}) {
  return (
    <Card>
      <div className="card-head">
        <h2>场景集列表</h2>
        <Tabs
          value={visibility}
          options={[{ value: "public", label: "公共" }, { value: "private", label: "私有" }]}
          onChange={onVisibility}
        />
      </div>
      <DataState loading={sets.loading} error={sets.error} empty={sets.items.length === 0} onRetry={sets.reload}>
        <VirtualList
          items={sets.items}
          rowHeight={112}
          height={440}
          keyOf={(item) => item.id}
          onEnd={sets.loadMore}
          render={(item) => (
            <div className="set-row">
              <div>
                <strong>{item.name}</strong>
                <small>v{item.current_version} · {item.member_count} 成员 · {formatTime(item.created_at)}</small>
              </div>
              <div className="row-actions">
                <StatusBadge status={item.visibility} />
                <StatusBadge status={item.frozen ? "frozen" : "draft"} />
              </div>
              <div className="row-actions">
                <button className="btn tiny ghost" onClick={() => onMembers(item)}>成员</button>
                {!item.frozen && <button className="btn tiny" onClick={() => onFreeze(item)}>冻结</button>}
                <button className="btn tiny ghost" onClick={() => onDerive(item)}>派生</button>
              </div>
            </div>
          )}
        />
      </DataState>
    </Card>
  );
}
