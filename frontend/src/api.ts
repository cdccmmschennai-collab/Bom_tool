import type { CombineKind, CombineTask, Job, JobPage, PartField, PartPage, Plant, PlantType, PlantTypeOption, Profile, User } from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

/** Fired when the server answers 401 (session expired or signed out elsewhere). */
export const SIGNED_OUT_EVENT = "bom:signed-out";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: "include", ...init });
  if (res.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new Error(message);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  me: () => request<User>("/api/auth/me"),

  login: (body: { username: string; password: string; remember: boolean }) =>
    request<User>("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),

  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  profile: () => request<Profile>("/api/auth/profile"),

  changePassword: (body: { current_password: string; new_password: string }) =>
    request<void>("/api/auth/change-password", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),

  plantTypes: () => request<PlantTypeOption[]>("/api/plant-types"),

  plants: (plantType?: PlantType) =>
    request<Plant[]>(plantType ? `/api/plants?plant_type=${encodeURIComponent(plantType)}` : "/api/plants"),

  convert: (params: { plantType: PlantType; plantId: number | null; file: File }) => {
    const form = new FormData();
    form.append("plant_type", params.plantType);
    if (params.plantId) form.append("plant_id", String(params.plantId));
    form.append("file", params.file);
    return request<Job>("/api/jobs", { method: "POST", body: form });
  },

  jobs: (params: { limit: number; offset: number; search?: string; dateFrom?: string; dateTo?: string }) => {
    const q = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) });
    if (params.search) q.set("search", params.search);
    if (params.dateFrom) q.set("date_from", params.dateFrom);
    if (params.dateTo) q.set("date_to", params.dateTo);
    return request<JobPage>(`/api/jobs?${q.toString()}`);
  },

  deleteJob: (jobId: number) => request<void>(`/api/jobs/${jobId}`, { method: "DELETE" }),

  combine: (jobIds: number[], kind: CombineKind) =>
    request<CombineTask>("/api/jobs/combine", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_ids: jobIds, kind }),
    }),

  combineStatus: (taskId: number) => request<CombineTask>(`/api/jobs/combine/${taskId}`),

  combineFileUrl: (taskId: number) => `${BASE}/api/jobs/combine/${taskId}/file`,

  parts: (params: { field: PartField; q: string; limit: number; offset: number }) => {
    const q = new URLSearchParams({
      field: params.field, q: params.q, limit: String(params.limit), offset: String(params.offset),
    });
    return request<PartPage>(`/api/parts?${q.toString()}`);
  },

  /** Excel of every record of a search (all records when no search is given). */
  partsExportUrl: (search: { field: PartField; q: string } | null) =>
    `${BASE}/api/parts/export${search ? `?${new URLSearchParams({ field: search.field, q: search.q }).toString()}` : ""}`,

  outputUrl: (jobId: number) => `${BASE}/api/jobs/${jobId}/output`,
  submissionUrl: (jobId: number) => `${BASE}/api/jobs/${jobId}/submission`,
  inputUrl: (jobId: number) => `${BASE}/api/jobs/${jobId}/input`,
};
