import { useState } from "react";
import { api } from "../api";
import { useAsync } from "../hooks";
import { Card, DataState, PageHeader, StatusBadge, TextField } from "../components/ui";
import type { UserAccount } from "../types";

interface UserForm {
  username: string;
  password: string;
  display_name: string;
  role: "super_admin" | "admin" | "user";
  status: "active" | "disabled";
  project: string;
  max_priority: string;
  max_daily_cases: string;
  max_running_cases: string;
}

function emptyForm(): UserForm {
  return {
    username: "",
    password: "",
    display_name: "",
    role: "user",
    status: "active",
    project: "default",
    max_priority: "5",
    max_daily_cases: "",
    max_running_cases: ""
  };
}

const ROLE_LABEL: Record<UserAccount["role"], string> = {
  super_admin: "超级管理员",
  admin: "管理员",
  user: "普通用户"
};

function optionalNumber(value: string): number | null {
  return value.trim() ? Number(value) : null;
}

export function Users() {
  const users = useAsync(() => api.users.list(), []);
  const [form, setForm] = useState<UserForm>(emptyForm);
  const [editing, setEditing] = useState<UserAccount | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  function set<K extends keyof UserForm>(key: K, value: UserForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function edit(user: UserAccount) {
    setEditing(user);
    setError("");
    setNotice("");
    setForm({
      username: user.username,
      password: "",
      display_name: user.display_name,
      role: user.role,
      status: user.status,
      project: user.project,
      max_priority: String(user.max_priority),
      max_daily_cases: user.max_daily_cases?.toString() || "",
      max_running_cases: user.max_running_cases?.toString() || ""
    });
  }

  async function save() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const base = {
        display_name: form.display_name,
        role: form.role,
        status: form.status,
        project: form.project,
        max_priority: Number(form.max_priority),
        max_daily_cases: optionalNumber(form.max_daily_cases),
        max_running_cases: optionalNumber(form.max_running_cases)
      };
      if (editing) {
        const body: Record<string, unknown> = { ...base };
        if (form.password) body.password = form.password;
        await api.users.update(editing.id, body);
        setNotice(`账号 ${editing.username} 已更新`);
      } else {
        await api.users.create({ ...base, username: form.username, password: form.password });
        setNotice(`账号 ${form.username} 已创建`);
      }
      setEditing(null);
      setForm(emptyForm());
      users.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <PageHeader title="账号与额度管理" subtitle="超级管理员可配置角色、最高优先级、并发与 CPU/内存/GPU 额度" />
      <div className="grid two">
        <Card>
          <div className="card-head">
            <h2>{editing ? `编辑账号：${editing.username}` : "新建账号"}</h2>
            {editing && <button className="btn tiny ghost" onClick={() => { setEditing(null); setForm(emptyForm()); }}>取消编辑</button>}
          </div>
          <TextField label="用户名" value={form.username} onChange={(value) => set("username", value)} />
          <TextField
            label={editing ? "重置密码（留空不修改）" : "密码（至少 8 位）"}
            type="password"
            value={form.password}
            onChange={(value) => set("password", value)}
          />
          <TextField label="显示名称" value={form.display_name} onChange={(value) => set("display_name", value)} />
          <div className="row">
            <label className="field">
              <span>角色</span>
              <select value={form.role} onChange={(event) => set("role", event.target.value as UserForm["role"])}>
                <option value="user">普通用户</option>
                <option value="admin">管理员</option>
                <option value="super_admin">超级管理员</option>
              </select>
            </label>
            <label className="field">
              <span>状态</span>
              <select value={form.status} onChange={(event) => set("status", event.target.value as UserForm["status"])}>
                <option value="active">启用</option>
                <option value="disabled">禁用</option>
              </select>
            </label>
          </div>
          <TextField label="项目" value={form.project} onChange={(value) => set("project", value)} />
          <div className="row">
            <TextField label="最高优先级 0-9" type="number" value={form.max_priority} onChange={(value) => set("max_priority", value)} />
            <TextField label="每日最大 cases" type="number" value={form.max_daily_cases} onChange={(value) => set("max_daily_cases", value)} />
            <TextField label="最大并发 cases" type="number" value={form.max_running_cases} onChange={(value) => set("max_running_cases", value)} />
          </div>
          {error && <div className="inline-error">{error}</div>}
          {notice && <div className="notice">{notice}</div>}
          <button className="btn" onClick={save} disabled={busy || (!editing && (!form.username || !form.password))}>
            {busy ? "保存中…" : editing ? "保存修改" : "创建账号"}
          </button>
        </Card>
        <Card>
          <h2>账号列表</h2>
          <DataState loading={users.loading} error={users.error} empty={!users.data?.items.length} onRetry={users.reload}>
            <div className="user-list">
              {users.data?.items.map((user) => (
                <div className="user-row" key={user.id}>
                  <div>
                    <strong>{user.username}</strong>
                    <small>{user.display_name} · {user.project}</small>
                  </div>
                  <div className="row-actions">
                    <span className={`badge role-${user.role}`}>{ROLE_LABEL[user.role]}</span>
                    <StatusBadge status={user.status} />
                  </div>
                  <span className="muted">P≤{user.max_priority}</span>
                  <span className="muted">
                    每日 {user.max_daily_cases ?? "∞"} cases · 并发 {user.max_running_cases ?? "∞"}
                  </span>
                  <button className="btn tiny ghost" onClick={() => edit(user)}>编辑</button>
                </div>
              ))}
            </div>
          </DataState>
        </Card>
      </div>
    </div>
  );
}
