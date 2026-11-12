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
  Task,
  TaskSummary,
  CaseRun
} from "./types";

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
  const response = await fetch(BASE + path, { ...init, headers });
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

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key === "size" ? "page_size" : key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

type Json = Record<string, unknown>;

export const api = {
  health: () => request<{ status: string }>("/health"),
  overview: () => request<Overview>("/stats/overview"),
  audit: (cursor?: string) => request<Page<Json>>(`/audit${query({ cursor })}`),

  scenarios: {
    list: (params: { search?: string; tag?: string; status?: string; cursor?: string; size?: number }) =>
      request<Page<Scenario>>(`/scenarios${query(params)}`),
    get: (id: string) => request<ScenarioDetail>(`/scenarios/${id}`),
    create: (body: Json) => request<ScenarioDetail>("/scenarios", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: Json) =>
      request<ScenarioDetail>(`/scenarios/${id}`, { method: "PUT", body: JSON.stringify(body) }),
    versions: (id: string) => request<{ items: Json[] }>(`/scenarios/${id}/versions`),
    remove: (id: string) => request<Json>(`/scenarios/${id}`, { method: "DELETE" })
  },

  sets: {
    list: (params: { frozen?: boolean; cursor?: string; size?: number }) =>
      request<Page<SetSummary>>(`/sets${query(params)}`),
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
    templates: () => request<{ items: MetricTemplate[] }>("/metrics/templates")
  },

  tasks: {
    list: (params: { status?: string; priority?: number; search?: string; cursor?: string; size?: number }) =>
      request<Page<Task>>(`/tasks${query(params)}`),
    get: (id: string) => request<Task>(`/tasks/${id}`),
    submit: (body: Json) => request<Task>("/tasks", { method: "POST", body: JSON.stringify(body) }),
    cases: (id: string, params: { status?: string; cursor?: string; size?: number }) =>
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
