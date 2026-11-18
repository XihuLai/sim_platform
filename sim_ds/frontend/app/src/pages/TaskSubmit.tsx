import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { Card, DataState, PageHeader, TextField } from "../components/ui";
import type { SetSummary } from "../types";

const ENV_KEYS = new Set([
  "SIM_SEED", "LOG_LEVEL", "SCENARIO_ID", "TASK_ID",
  "CASE_RUN_ID", "SIM_ENGINE", "METRIC_CONFIG", "OUTPUT_DIR"
]);

function parseEnv(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const index = line.indexOf("=");
    if (index <= 0) continue;
    const key = line.slice(0, index).trim();
    if (!ENV_KEYS.has(key)) throw new Error(`env 白名单不允许 ${key}`);
    result[key] = line.slice(index + 1).trim();
  }
  return result;
}

export function TaskSubmit() {
  const navigate = useNavigate();
  const sets = useAsync(() => api.sets.list({ frozen: true, size: 100 }), []);
  const [setId, setSetId] = useState("");
  const [name, setName] = useState("");
  const [priority, setPriority] = useState("5");
  const [binary, setBinary] = useState("log-resim");
  const [binaryUri, setBinaryUri] = useState("");
  const [binaryChecksum, setBinaryChecksum] = useState("");
  const [engineOpen, setEngineOpen] = useState(false);
  const engines = [
    { value: "log-resim", label: "内置确定性引擎" },
    { value: "mock", label: "Mock 执行器" },
    { value: "mock_case", label: "单 case 模拟脚本 test_mock_run_case.py" },
    { value: "sim_engine", label: "sim_engine" }
  ];
  const [envText, setEnvText] = useState("SIM_SEED=42\nLOG_LEVEL=info");
  const [timeout, setTimeoutSec] = useState("120");
  const [retry, setRetry] = useState("1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selected = useMemo<SetSummary | undefined>(() => sets.data?.items.find((item) => item.id === setId), [sets.data, setId]);

  async function submit() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const task = await api.tasks.submit({
        name: name || `仿真任务 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`,
        set_id: setId,
        set_version: selected?.current_version,
        priority: Number(priority),
        runtime: {
          binary_id: binary,
          ...(binaryUri
            ? { binary_uri: binaryUri, binary_checksum: binaryChecksum }
            : {}),
          args: [],
          env: parseEnv(envText),
          resource: { cpu: 1, mem_gb: 1, gpu: 0 },
          timeout_sec: Number(timeout),
          retry: { max: Number(retry), on: ["timeout", "worker_lost"] }
        },
        metrics: [],
        batch: { max_cases: 0, shard_size: 1000 },
        seed: Number(envText.match(/SIM_SEED=(\d+)/)?.[1] || 42)
      });
      if (task.status === "expanding" || task.total_cases > 500) {
        setNotice(`任务 ${task.task_id} 已接受，${selected?.member_count || task.total_cases} 个 case 将异步分批展开。`);
      }
      navigate(`/tasks/${task.task_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <PageHeader title="发起仿真" subtitle="只能选择冻结场景集；RuntimeConfig 只允许白名单 env 与模板变量" />
      <DataState loading={sets.loading} error={sets.error} empty={!sets.data?.items.length} onRetry={sets.reload}>
        <div className="grid two">
          <Card>
            <h2>任务与场景集</h2>
            <label className="field">
              <span>冻结场景集</span>
              <select value={setId} onChange={(event) => setSetId(event.target.value)}>
                <option value="">请选择</option>
                {sets.data?.items.map((item) => (
                  <option key={item.id} value={item.id}>{item.name} · v{item.current_version} · {item.member_count} cases</option>
                ))}
              </select>
            </label>
            <TextField
              label="Worker Binary OSS URI（K8s 执行必填，s3://bucket/key）"
              value={binaryUri}
              onChange={setBinaryUri}
            />
            {binaryUri && (
              <TextField
                label="Binary SHA-256（sha256: 后接 64 位小写十六进制）"
                value={binaryChecksum}
                onChange={setBinaryChecksum}
              />
            )}
            <TextField label="任务名称" value={name} onChange={setName} />
            <div className="row">
              <TextField label="优先级 0-9" value={priority} onChange={setPriority} type="number" />
              <TextField label="超时秒" value={timeout} onChange={setTimeoutSec} type="number" />
              <TextField label="重试次数" value={retry} onChange={setRetry} type="number" />
            </div>
            {selected && selected.member_count > 500 && (
              <div className="notice">该集合 {selected.member_count} 个 case，提交后将进入异步 expanding，由后台按 1000/批展开。</div>
            )}
          </Card>
          <Card>
            <h2>RuntimeConfig</h2>
            <label className="field">
              <span>Binary / 引擎地址</span>
              <div
                className="engine-picker"
                onBlur={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                    setEngineOpen(false);
                  }
                }}
              >
                <div className="engine-input-row">
                  <input
                    value={binary}
                    onFocus={() => setEngineOpen(true)}
                    onChange={(event) => setBinary(event.target.value)}
                    placeholder="log-resim / mock / /opt/sim/bin/engine"
                  />
                  <button type="button" className="btn tiny ghost" onClick={() => setEngineOpen((value) => !value)}>
                    ▾
                  </button>
                </div>
                {engineOpen && (
                  <div className="engine-dropdown">
                    {engines.map((engine) => (
                      <button
                        type="button"
                        key={engine.value}
                        className={engine.value === binary ? "active" : ""}
                        onClick={() => {
                          setBinary(engine.value);
                          setEngineOpen(false);
                        }}
                      >
                        <strong>{engine.value}</strong>
                        <small>{engine.label}</small>
                      </button>
                    ))}
                    <p className="muted">也可以直接输入本地可执行文件路径。</p>
                  </div>
                )}
              </div>
            </label>
            <label className="field">
              <span>Env（KEY=VALUE，每行一个）</span>
              <textarea rows={5} value={envText} onChange={(event) => setEnvText(event.target.value)} />
            </label>
            <p className="muted">
              默认输出目录：/tmp/&lt;task_id&gt;/&lt;case_run_id&gt;/。
              可在 Env 中设置 OUTPUT_DIR 覆盖；未填写 Args 时由执行器自动注入
              --scenario/--out/--seed。
            </p>
          </Card>
        </div>
        {error && <div className="inline-error">{error}</div>}
        {notice && <div className="notice">{notice}</div>}
        <div className="actions">
          <button className="btn" onClick={submit} disabled={busy || !setId}>{busy ? "提交中…" : "提交任务"}</button>
        </div>
      </DataState>
    </div>
  );
}
