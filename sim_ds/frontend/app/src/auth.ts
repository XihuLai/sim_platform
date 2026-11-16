export interface CurrentUser {
  username: string;
  role: "super_admin" | "admin" | "user";
  project: string;
  admin: boolean;
  max_priority: number;
  max_running_cases?: number | null;
  max_cpu?: number | null;
  max_mem_gb?: number | null;
  max_gpu?: number | null;
}

const TOKEN_KEY = "sim.token";
const USER_KEY = "sim.currentUser";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function currentUser(): CurrentUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as CurrentUser;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: CurrentUser): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  localStorage.setItem("sim.project", user.project || "default");
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}
