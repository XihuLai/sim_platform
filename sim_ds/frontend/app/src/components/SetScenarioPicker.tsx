import type { Scenario } from "../types";
import { Card, DataState } from "./ui";
import { TagFilter } from "./TagFilter";

export interface SelectedScenario {
  scenario: Scenario;
  version: number;
}

export interface ScenarioVersionOption {
  version: number;
  publish_state: string;
}

interface Props {
  scenarios: Scenario[];
  loading: boolean;
  error: string | null;
  name: string;
  visibility: "private" | "public";
  search: string;
  tagExpr: string;
  selected: Record<string, SelectedScenario>;
  versions: Record<string, ScenarioVersionOption[]>;
  creating: boolean;
  createError: string | null;
  onName: (value: string) => void;
  onVisibility: (value: "private" | "public") => void;
  onSearch: (value: string) => void;
  onTagExpr: (value: string) => void;
  onReload: () => void;
  onToggle: (scenario: Scenario) => void;
  onVersion: (scenarioId: string, version: number) => void;
  onCreate: () => void;
}

function optionsFor(
  entry: SelectedScenario,
  versions: Record<string, ScenarioVersionOption[]>
): ScenarioVersionOption[] {
  const rows = (versions[entry.scenario.id] || [])
    .filter((item) => item.publish_state === "published")
    .sort((left, right) => right.version - left.version);
  if (rows.some((item) => item.version === entry.version)) return rows;
  return [{ version: entry.version, publish_state: "published" }, ...rows];
}

export function SetScenarioPicker({
  scenarios,
  loading,
  error,
  name,
  visibility,
  search,
  tagExpr,
  selected,
  versions,
  creating,
  createError,
  onName,
  onVisibility,
  onSearch,
  onTagExpr,
  onReload,
  onToggle,
  onVersion,
  onCreate
}: Props) {
  const selectedRows = Object.values(selected);

  return (
    <Card>
      <h2>创建场景集</h2>
      <div className="row">
        <label className="field">
          <span>场景集名称</span>
          <input
            placeholder="请输入场景集名称"
            value={name}
            onChange={(event) => onName(event.target.value)}
          />
        </label>
        <label className="field">
          <span>可见性</span>
          <select
            value={visibility}
            onChange={(event) => onVisibility(event.target.value as "private" | "public")}
          >
            <option value="private">私有</option>
            <option value="public">公共</option>
          </select>
        </label>
      </div>
      <div className="picker-filters">
        <input
          placeholder="按场景名称或 ID 筛选"
          value={search}
          onChange={(event) => onSearch(event.target.value)}
        />
        <TagFilter value={tagExpr} onChange={onTagExpr} />
        <button className="btn tiny ghost" onClick={onReload}>刷新</button>
      </div>
      <DataState loading={loading} error={error} empty={!loading && scenarios.length === 0}>
        <div className="check-grid">
          {scenarios.map((scenario) => (
            <label key={scenario.id} className="check-row">
              <input
                type="checkbox"
                checked={Boolean(selected[scenario.id])}
                onChange={() => onToggle(scenario)}
              />
              <span>
                {scenario.name}
                <small>{scenario.id}</small>
              </span>
              <small>v{scenario.version}</small>
            </label>
          ))}
        </div>
      </DataState>

      {selectedRows.length > 0 && (
        <div className="selected-scenarios">
          <h3>已选择 {selectedRows.length} 个场景，可指定成员版本</h3>
          {selectedRows.map((entry) => (
            <div key={entry.scenario.id} className="selected-row">
              <div>
                <strong>{entry.scenario.name}</strong>
                <small>{entry.scenario.id}</small>
              </div>
              <label>
                版本
                <select
                  value={entry.version}
                  onChange={(event) => onVersion(entry.scenario.id, Number(event.target.value))}
                >
                  {optionsFor(entry, versions).map((option) => (
                    <option key={option.version} value={option.version}>v{option.version}</option>
                  ))}
                </select>
              </label>
              <button className="btn tiny ghost" onClick={() => onToggle(entry.scenario)}>移除</button>
            </div>
          ))}
        </div>
      )}

      {createError && <div className="inline-error">{createError}</div>}
      <button className="btn" onClick={onCreate} disabled={creating || selectedRows.length === 0}>
        {creating ? "创建中…" : `创建场景集（已选 ${selectedRows.length}）`}
      </button>
    </Card>
  );
}
