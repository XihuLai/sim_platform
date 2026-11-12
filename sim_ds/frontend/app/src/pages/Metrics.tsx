import { useMemo, useState } from "react";
import { api } from "../api";
import { useAsync } from "../hooks";
import { Card, DataState, PageHeader, StatusBadge, Tabs } from "../components/ui";

export function Metrics() {
  const [tab, setTab] = useState<"tree" | "templates">("tree");
  const [selected, setSelected] = useState<string>("");
  const state = useAsync(async () => {
    const [categories, types, defs, templates] = await Promise.all([
      api.metrics.categories(),
      api.metrics.types(),
      api.metrics.defs(),
      api.metrics.templates()
    ]);
    return {
      categories: categories.items,
      types: types.items,
      defs: defs.items,
      templates: templates.items
    };
  }, []);
  const activeDef = useMemo(
    () => state.data?.defs.find((item) => item.id === selected) || state.data?.defs[0],
    [state.data, selected]
  );

  return (
    <div className="page">
      <PageHeader title="Metric 管理" subtitle="固定 5 类 → 类型树 → 模板 env_schema → 定义版本 → 场景实例" />
      <DataState loading={state.loading} error={state.error} empty={false} onRetry={state.reload}>
        <Tabs
          value={tab}
          onChange={setTab}
          options={[{ value: "tree", label: "五层结构" }, { value: "templates", label: "模板 Schema" }]}
        />
        {tab === "tree" ? (
          <div className="grid two">
            <Card>
              <h2>分类 / 类型 / 定义</h2>
              <div className="metric-tree">
                {state.data?.categories.map((category) => (
                  <div key={String(category.id)} className="tree-group">
                    <strong>{String(category.name)} <small>{String(category.id)}</small></strong>
                    {state.data?.types.filter((type) => type.category_id === category.id).map((type) => (
                      <div key={type.id} className="tree-type">
                        <span>{type.name}</span>
                        {state.data?.defs.filter((definition) => definition.type_id === type.id).map((definition) => (
                          <button
                            key={`${definition.id}@${definition.version}`}
                            className={`tree-def ${activeDef?.id === definition.id ? "active" : ""}`}
                            onClick={() => setSelected(definition.id)}
                          >
                            {definition.name}
                            <small>v{definition.version}</small>
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </Card>
            <Card>
              <h2>定义详情</h2>
              {activeDef ? (
                <>
                  <div className="meta-line">
                    <code>{activeDef.id}@v{activeDef.version}</code>
                    <StatusBadge status={activeDef.status} />
                    <span>level {activeDef.level || "—"}</span>
                    <span>{activeDef.business_type || "—"}</span>
                  </div>
                  <p>{activeDef.description || "暂无描述"}</p>
                  <h3>触发模板</h3>
                  <TagList items={activeDef.trigger_templates.map((item) => `#${item.template_id}${item.required ? " 必需" : ""}`)} />
                  <h3>检测函数</h3>
                  <TagList items={activeDef.function_templates.map((item) => `#${item.template_id}${item.required ? " 必需" : ""}`)} />
                  <h3>params_schema 预览</h3>
                  <pre className="json small">{JSON.stringify(activeDef, null, 2)}</pre>
                </>
              ) : <p className="muted">暂无定义</p>}
            </Card>
          </div>
        ) : (
          <div className="grid two">
            {state.data?.templates.map((template) => (
              <Card key={template.id}>
                <h2>#{template.id} {template.name} <small>{template.kind}</small></h2>
                <pre className="json small">{JSON.stringify(template.env_schema, null, 2)}</pre>
                <h3>env 示例</h3>
                <pre className="json small">{JSON.stringify(template.env_example, null, 2)}</pre>
              </Card>
            ))}
          </div>
        )}
      </DataState>
    </div>
  );
}

function TagList({ items }: { items: string[] }) {
  return <div className="tags">{items.map((item) => <span key={item}>{item}</span>)}</div>;
}
