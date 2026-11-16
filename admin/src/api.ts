export type Row = Record<string, unknown>;

const API_BASE = (import.meta.env.VITE_API_URL || "/api/v1").replace(/\/+$/, "");
const TOKEN_KEY = "sherail_admin_token";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
}

export function apiUrl(path: string) {
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  token = getToken(),
): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(apiUrl(path), { ...options, headers });
  } catch {
    throw new ApiError("Could not reach the server. Check your connection and API URL.", 0);
  }

  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      const detail = body?.detail ?? body?.message;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) {
        message = detail.map((item) => item?.msg || JSON.stringify(item)).join(" ");
      }
    } catch {
      // Keep the status-based message for non-JSON responses.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function fetchImage(path: string, token: string) {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ApiError("Image could not be loaded. Check your connection.", 0);
  }
  if (!response.ok) throw new ApiError(`Image request failed (${response.status}).`, response.status);
  return URL.createObjectURL(await response.blob());
}

export function rowsFrom(value: unknown): Row[] {
  if (Array.isArray(value)) return value.filter((item): item is Row => !!item && typeof item === "object");
  if (!value || typeof value !== "object") return [];
  const result = value as Record<string, unknown>;
  for (const key of ["items", "results", "users", "alerts", "reports", "assistance_points", "railway_assistance"]) {
    if (Array.isArray(result[key])) return rowsFrom(result[key]);
  }
  return [];
}

export function display(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function dateLabel(value: unknown) {
  if (typeof value !== "string" || !value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function isSessionError(error: unknown) {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}
