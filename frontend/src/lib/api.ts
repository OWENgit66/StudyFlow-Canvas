import type { Course, DashboardData, KnowledgeResponse, Resource, SyncResult, SyncScope, Week } from "./types";

// Blank uses Next's same-origin proxy. No backend credential belongs here.
const base = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
export class APIError extends Error {
  constructor(public status: number) { super("StudyFlow could not complete this request."); }
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`${base}/api${path}`, { cache: "no-store", ...init }); }
  catch { throw new APIError(0); }
  // Error bodies may contain operational details. Never render them.
  if (!response.ok) throw new APIError(response.status);
  try { return await response.json() as T; }
  catch { throw new APIError(502); }
}
export const api = {
  dashboard: () => request<DashboardData>("/study/dashboard"),
  course: (id: number) => request<Course>(`/courses/${id}`),
  weeks: (id: number) => request<Week[]>(`/courses/${id}/weeks`),
  week: (id: number) => request<Week>(`/weeks/${id}`),
  resources: (id: number) => request<Resource[]>(`/weeks/${id}/resources`),
  async knowledge(id: number): Promise<KnowledgeResponse | null> {
    try {
      const result = await request<KnowledgeResponse>(`/resources/${id}/knowledge`);
      return result.stale === false && result.resource_id === id ? result : null;
    } catch (error) {
      if (error instanceof APIError && error.status === 404) return null;
      throw error;
    }
  },
  activeSync: () => request<SyncResult | null>("/sync/current", { signal: AbortSignal.timeout(15000) }),
  syncStatus: (id: number) => request<SyncResult>(`/sync/${id}`, { signal: AbortSignal.timeout(15000) }),
  cancelSync: (id: number) => request<SyncResult>(`/sync/${id}/cancel`, { method: "POST", signal: AbortSignal.timeout(15000) }),
  sync: (scope: SyncScope) => request<SyncResult>("/sync?background=true", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(scope), signal: AbortSignal.timeout(15000),
  }),
};
export function fileURL(id: number, page?: number, download = false): string {
  return `${base}/api/resources/${id}/file${download ? "?download=true" : ""}${page ? `#page=${page}` : ""}`;
}
