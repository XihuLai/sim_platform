import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync, useInterval } from "../hooks";
import { clearSession, currentUser } from "../auth";
import { formatTime } from "./ui";

const NAV = [
  { to: "/scenarios", label: "场景列表", icon: "▤" },
  { to: "/scenarios/new", label: "场景创建", icon: "＋" },
  { to: "/metrics", label: "Metric 管理", icon: "◈" },
  { to: "/sets", label: "场景集", icon: "▦" },
  { to: "/tasks/new", label: "发起仿真", icon: "▶" },
  { to: "/tasks", label: "任务列表", icon: "☰" },
  { to: "/queue", label: "队列看板", icon: "◷" },
  { to: "/stats", label: "数据统计", icon: "◫" },
  { to: "/playback", label: "数据播放", icon: "◉" }
];

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const user = currentUser();
  const [project, setProject] = useState(localStorage.getItem("sim.project") || "default");
  const overview = useAsync(() => api.overview(), [project, location.pathname]);
  const isAdmin = Boolean(user?.admin) || user?.role === "admin" || user?.role === "super_admin";
  const nav = isAdmin ? [...NAV, { to: "/admin/users", label: "账号与额度", icon: "⚙" }] : NAV;
  const stats = overview.data;
  useInterval(() => overview.reload(), 5000);

  useEffect(() => {
    localStorage.setItem("sim.project", project);
  }, [project]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo">S</span>
          <div>
            <strong>SimCloud</strong>
            <small>自动驾驶仿真云</small>
          </div>
        </div>
        <nav>
          {nav.map((item) => (
            <NavLink key={item.to} to={item.to} end>
              <i>{item.icon}</i>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="side-foot">
          <div className="account-box">
            <strong>{user?.username || "未登录"}</strong>
            <small>{user?.role || "—"}</small>
          </div>
          <label>
            项目
            <input value={project} onChange={(event) => setProject(event.target.value || "default")} />
          </label>
          <button
            className="btn tiny ghost side-logout"
            onClick={() => {
              void api.auth.logout().catch(() => undefined);
              clearSession();
              navigate("/login");
            }}
          >
            退出登录
          </button>
          <small>最近刷新 {formatTime(stats ? new Date().toISOString() : null)}</small>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="kpis">
            <Kpi label="场景" value={stats ? String(stats.scenarios) : "—"} />
            <Kpi label="任务" value={stats ? String(stats.tasks.reduce((sum, row) => sum + row.tasks, 0)) : "—"} />
            <Kpi label="通过率" value={stats ? `${stats.pass_rate}%` : "—"} tone="pass" />
            <Kpi label="队列深度" value={stats ? String(stats.queue_depth) : "—"} tone="queue" />
            <Kpi label="运行中" value={stats ? String(stats.running_cases) : "—"} tone="running" />
          </div>
          <span className={`health ${overview.error ? "down" : "up"}`}>{overview.error ? "服务异常" : "服务正常"}</span>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function Kpi({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className={`kpi ${tone}`}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}
