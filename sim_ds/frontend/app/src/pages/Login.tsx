import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../api";
import { getToken, setSession } from "../auth";

export function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("df_sim");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const result = await api.auth.login(username, password);
      setSession(result.token, result.user);
      navigate("/scenarios", { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  if (getToken()) {
    return <Navigate to="/scenarios" replace />;
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="brand login-brand">
          <span className="logo">S</span>
          <div>
            <strong>SimCloud</strong>
            <small>自动驾驶仿真云 · 账号登录</small>
          </div>
        </div>
        <label className="field">
          <span>用户名</span>
          <input value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label className="field">
          <span>密码</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void submit();
            }}
          />
        </label>
        {error && <div className="inline-error">{error}</div>}
        <button className="btn login-button" onClick={submit} disabled={busy}>
          {busy ? "登录中…" : "登录"}
        </button>
        <p className="muted">超级管理员：df_sim</p>
      </div>
    </div>
  );
}
