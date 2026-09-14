/**
 * Thin client for the FastAPI backend (PRD §13). Only routes the backend
 * owns go through here: project/run creation, run control, hearing
 * confirmation. Reads of assumptions/evidence/conflicts/verdicts/versions
 * go direct through `supabase-js` (see `lib/supabase/client.ts`), never
 * through this module.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  accessToken: string | undefined,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, body || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface TargetScope {
  geo: string;
  segment: string;
  tier?: string | null;
  period?: string | null;
}

export interface ProjectOut {
  id: string;
  user_id: string;
  name: string;
  archetype: string | null;
  archetype_confidence?: number;
  target_scope: TargetScope;
  created_at: string;
  updated_at: string;
}

export interface RunOut {
  id: string;
  project_id: string;
  user_id: string;
  kind: string;
  status:
    | "pending"
    | "hearing"
    | "investigating"
    | "cross_exam"
    | "deciding"
    | "complete"
    | "failed";
  thread_id: string;
  started_at: string;
  completed_at: string | null;
}

export interface RunEvent {
  id: number;
  run_id: string;
  ts: string;
  node: string;
  event: "node_start" | "node_end" | "llm_call" | "tool_call" | "fetch" | "error" | "interrupt";
  detail: Record<string, unknown> | null;
  latency_ms: number | null;
}

export const api = {
  createProject: (token: string, body: { name: string; pitch: string; target_scope: TargetScope }) =>
    request<ProjectOut>("/projects", token, { method: "POST", body: JSON.stringify(body) }),

  listProjects: (token: string) => request<ProjectOut[]>("/projects", token),

  getProject: (token: string, projectId: string) =>
    request<ProjectOut>(`/projects/${projectId}`, token),

  patchProject: (
    token: string,
    projectId: string,
    body: Partial<{ name: string; archetype: string; target_scope: TargetScope }>,
  ) =>
    request<ProjectOut>(`/projects/${projectId}`, token, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  startRun: (token: string, projectId: string, kind: string = "initial") =>
    request<{ run_id: string; status: string }>(`/projects/${projectId}/runs`, token, {
      method: "POST",
      body: JSON.stringify({ kind }),
    }),

  getRun: (token: string, runId: string) => request<RunOut>(`/runs/${runId}`, token),

  getRunEvents: (token: string, runId: string) =>
    request<RunEvent[]>(`/runs/${runId}/events`, token),

  confirmHearing: (
    token: string,
    runId: string,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    assumptions: Record<string, any>[],
  ) =>
    request<{ run_id: string; status: string }>(`/runs/${runId}/hearing/confirm`, token, {
      method: "POST",
      body: JSON.stringify({ assumptions }),
    }),

  cancelRun: (token: string, runId: string) =>
    request<RunOut>(`/runs/${runId}/cancel`, token, { method: "POST" }),
};
