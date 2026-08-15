import type {
  AdminMetrics,
  AdminModel,
  Alert,
  AuthResponse,
  CandidatesResponse,
  ChatMessageItem,
  ChatResponse,
  Conversation,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("prism_token");
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem("prism_token", token);
  else window.localStorage.removeItem("prism_token");
}

/* ---- demo-mode flag (used when no backend is connected yet) ---- */
export function setDemoModeFlag(on: boolean) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem("prism_demo", on ? "1" : "0");
}

export function getDemoModeFlag(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem("prism_demo") === "1";
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (resp.status === 204) return undefined as T;
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new ApiError(
      body?.error ?? "http_error",
      body?.message ?? `Request failed (${resp.status})`,
      resp.status,
    );
  }
  return body as T;
}

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

/* ------------------------------------------------------------------ auth */
export function register(email: string, password: string, name?: string) {
  return apiFetch<AuthResponse>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name: name }),
  });
}

export function login(email: string, password: string) {
  return apiFetch<AuthResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

/* ------------------------------------------------------------------ chat */
export async function sendChat(
  message: string,
  opts: { conversationId?: string | null; attachments?: string[] } = {},
): Promise<ChatResponse> {
  return apiFetch<ChatResponse>("/api/v1/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      conversation_id: opts.conversationId ?? null,
      attachments: opts.attachments ?? [],
      stream: false,
    }),
  });
}

/** SSE streaming chat: yields text deltas and the final request id. */
export async function* streamChat(
  message: string,
  opts: { conversationId?: string | null; attachments?: string[] } = {},
): AsyncGenerator<{ type: "token"; text: string } | { type: "done"; requestId: string }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      message,
      conversation_id: opts.conversationId ?? null,
      attachments: opts.attachments ?? [],
      stream: true,
    }),
  });
  if (!resp.ok || !resp.body) throw new ApiError("stream_error", "Streaming failed", resp.status);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let requestId = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const event = frame.match(/^event: (\w+)/m)?.[1];
      const data = frame.match(/^data: (.*)$/m)?.[1];
      if (!event || !data) continue;
      const payload = JSON.parse(data);
      if (event === "token" && payload.text) yield { type: "token", text: payload.text };
      if (event === "meta") requestId = payload.request_id;
      if (event === "done") yield { type: "done", requestId };
    }
  }
}

export function getCandidates(requestId: string, reveal = false) {
  return apiFetch<CandidatesResponse>(
    `/api/v1/chat/${requestId}/candidates${reveal ? "?reveal=true" : ""}`,
  );
}

export function sendFeedback(requestId: string, rating: 1 | -1, comment?: string) {
  return apiFetch<{ accepted: boolean }>(`/api/v1/chat/${requestId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ rating, comment }),
  });
}

export function listConversations() {
  return apiFetch<Conversation[]>("/api/v1/chat/conversations");
}

export function getConversation(id: string) {
  return apiFetch<{ conversation: Conversation; messages: ChatMessageItem[] }>(
    `/api/v1/chat/conversations/${id}`,
  );
}

/* ------------------------------------------------------------------ files */
export async function uploadFile(file: File): Promise<{ file_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const token = getToken();
  const resp = await fetch(`${API_BASE}/api/v1/files/upload`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new ApiError(body?.error ?? "upload_failed", body?.message ?? "Upload failed", resp.status);
  }
  return body as { file_id: string };
}

/* ------------------------------------------------------------------ admin */
export function adminMetrics() {
  return apiFetch<AdminMetrics>("/api/v1/admin/metrics");
}
export function adminModels() {
  return apiFetch<AdminModel[]>("/api/v1/admin/models");
}
export function adminAlerts() {
  return apiFetch<{ alerts: Alert[] }>("/api/v1/admin/alerts");
}

/* ------------------------------------------------------------------ privacy */
export function deleteMyData() {
  return apiFetch<{ deleted: Record<string, number>; account_deleted: boolean }>(
    "/api/v1/me/data",
    { method: "DELETE" },
  );
}
