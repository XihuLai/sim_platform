import type {
  ChunkPayload,
  DataSource,
  MetricDef,
  MetricTemplate,
  MetricType,
  Overview,
  Page,
  QueueStats,
  Scenario,
  ScenarioDetail,
  SetMember,
  SetSummary,
  TagOption,
  Task,
  TaskSummary,
  CaseRun,
  UserAccount
} from "./types";
import { clearSession, getToken, type CurrentUser } from "./auth";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  code: string;
  detail: unknown;
  status: number;
  constructor(status: number, code: string, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function projectHeader(): Record<string, string> {
  const project = localStorage.getItem("sim.project") || "default";
  return { "X-Project": project, "X-User": localStorage.getItem("sim.user") || "web" };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  for (const [key, value] of Object.entries(projectHeader())) headers.set(key, value);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(BASE + path, { ...init, headers });
  if (response.status === 401 && !path.startsWith("/auth/login")) {
    clearSession();
    if (window.location.pathname !== "/login") window.location.href = "/login";
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      body.code || "HTTP_ERROR",
      body.message || response.statusText,
      body.detail
    );
  }
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | boolean | string[] | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    const name = key === "size" ? "page_size" : key;
    if (Array.isArray(value)) {
      for (const item of value) search.append(name, item);
    } else {
      search.set(name, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

type Json = Record<string, unknown>;

export const api = {
  auth: {
    login: (username: string, password: string) =>
      request<{ token: string; expires_at: string; user: CurrentUser }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password })
      }),
    me: () => request<CurrentUser>("/auth/me"),
    logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" })
  },

  users: {
    list: () => request<{ items: UserAccount[] }>("/users"),
    create: (body: Json) => request<UserAccount>("/users", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: Json) =>
      request<UserAccount>(`/users/${id}`, { method: "PUT", body: JSON.stringify(body) })
  },

  health: () => request<{ status: string }>("/health"),
  overview: () => request<Overview>("/stats/overview"),
  userStats: (days: number) => request<{
    days: number;
    items: Array<{ owner: string; tasks: number; cases: number; succeeded: number; passed: number }>;
    totals: { tasks: number; cases: number; succeeded: number; passed: number };
  }>(`/stats/users?days=${days}`),
  audit: (cursor?: string) => request<Page<Json>>(`/audit${query({ cursor })}`),

  tags: {
    list: (params: { search?: string; size?: number }) =>
      request<{ items: TagOption[] }>(`/tags${query(params)}`)
  },

  scenarios: {
    list: (params: {
      search?: string;
      tag?: string;
      tags?: string[];
      tag_expr?: string;
      tag_mode?: "and" | "or";
      status?: string;
      cursor?: string;
      size?: number;
    }) => request<Page<Scenario>>(`/scenarios${query(params)}`),
    get: (id: string) => request<ScenarioDetail>(`/scenarios/${id}`),
    create: (body: Json) => request<ScenarioDetail>("/scenarios", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: Json) =>
      request<ScenarioDetail>(`/scenarios/${id}`, { method: "PUT", body: JSON.stringify(body) }),
    copy: (id: string, body: Json) =>
      request<ScenarioDetail>(`/scenarios/${id}:copy`, { method: "POST", body: JSON.stringify(body) }),
    versions: (id: string) => request<{ items: Json[] }>(`/scenarios/${id}/versions`),
    remove: (id: string, hard = false) =>
      request<Json>(`/scenarios/${id}${hard ? "?hard=true" : ""}`, { method: "DELETE" })
  },

  sets: {
    list: (params: {
      frozen?: boolean;
      visibility?: "private" | "public";
      cursor?: string;
      size?: number;
    }) => request<Page<SetSummary>>(`/sets${query(params)}`),
    get: (id: string) => request<SetSummary>(`/sets/${id}`),
    create: (body: Json) => request<SetSummary>("/sets", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: Json) =>
      request<SetSummary>(`/sets/${id}`, { method: "PUT", body: JSON.stringify(body) }),
    freeze: (id: string) => request<SetSummary>(`/sets/${id}:freeze`, { method: "POST" }),
    derive: (id: string, body: Json) =>
      request<SetSummary>(`/sets/${id}:derive`, { method: "POST", body: JSON.stringify(body) }),
    members: (id: string, cursor?: string) =>
      request<{ items: SetMember[]; next_cursor: string | null; version: number }>(
        `/sets/${id}/members${query({ cursor })}`
      )
  },

  metrics: {
    categories: () => request<{ items: Json[] }>("/metrics/categories"),
    types: () => request<{ items: MetricType[] }>("/metrics/types"),
    defs: () => request<{ items: MetricDef[] }>("/metrics/defs"),
    createDef: (body: Json) => request<MetricDef>("/metrics/defs", { method: "POST", body: JSON.stringify(body) }),
    updateDef: (id: string, body: Json) =>
      request<MetricDef>(`/metrics/defs/${id}`, { method: "PUT", body: JSON.stringify(body) }),
    deleteDef: (id: string) =>
      request<{ id: string; status: string }>(`/metrics/defs/${id}`, { method: "DELETE" }),
    templates: () => request<{ items: MetricTemplate[] }>("/metrics/templates")
  },

  tasks: {
    list: (params: { status?: string; priority?: number; search?: string; mine?: boolean; cursor?: string; size?: number }) =>
      request<Page<Task>>(`/tasks${query(params)}`),
    get: (id: string) => request<Task>(`/tasks/${id}`),
    submit: (body: Json) => request<Task>("/tasks", { method: "POST", body: JSON.stringify(body) }),
    cases: (id: string, params: { status?: string; outcome?: string; cursor?: string; size?: number }) =>
      request<{ items: CaseRun[]; next_cursor: string | null }>(`/tasks/${id}/cases${query(params)}`),
    summary: (id: string) => request<TaskSummary>(`/tasks/${id}/summary`),
    control: (id: string, command: "pause" | "resume" | "cancel", requestId: string, reason = "") =>
      request<Json>(`/tasks/${id}:${command}`, {
        method: "POST",
        body: JSON.stringify({ request_id: requestId, reason })
      }),
    queue: () => request<QueueStats>("/queue/stats")
  },

  playback: {
    list: (params: { cursor?: string; size?: number }) => request<Page<DataSource>>(`/sources${query(params)}`),
    get: (id: string) => request<DataSource>(`/sources/${id}`),
    channels: (id: string) => request<Json>(`/sources/${id}/channels`),
    index: (id: string) => request<Json>(`/sources/${id}:index`, { method: "POST" }),
    chunk: (id: string, channel: string, ts: number, span: number) =>
      request<ChunkPayload>(`/sources/${id}/chunk${query({ channel, ts, span })}`),
    frame: (id: string, channel: string, ts: number) =>
      request<Json>(`/sources/${id}/frame${query({ channel, ts })}`),
    create: (body: Json) => request<DataSource>("/sources", { method: "POST", body: JSON.stringify(body) }),
    extract: (body: Json) => request<DataSource>("/sources:extract", { method: "POST", body: JSON.stringify(body) })
  }
};

export type { Page };
