import type { CombineKind, CombineTask, Job, JobPage, PartField, PartPage, Plant, PlantType, PlantTypeOption, Profile, User } from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

/** Fired when the server answers 401 (session expired or signed out elsewhere). */
export const SIGNED_OUT_EVENT = "bom:signed-out";

/** Error text for a failed response: the API's `detail` when there is one, else "status statusText". */
function errorMessage(status: number, statusText: string, body: unknown): string {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d: { msg: string }) => d.msg).join("; ");
  return `${status} ${statusText}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: "include", ...init });
  if (res.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      /* not JSON */
    }
    throw new Error(errorMessage(res.status, res.statusText, body));
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

/** POST with upload progress (fetch cannot report it). Same credentials, errors and sign-out event as request(). */
function upload<T>(path: string, body: FormData, onUploadProgress: (fraction: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}${path}`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && e.total > 0) onUploadProgress(e.loaded / e.total); };
    xhr.upload.onload = () => onUploadProgress(1); // every byte sent - the server is converting now
    xhr.onerror = () => reject(new TypeError("Failed to fetch"));
    xhr.onabort = () => reject(new Error("The upload was cancelled."));
    xhr.onload = () => {
      if (xhr.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
      let json: unknown;
      let parsed = true;
      try {
        json = xhr.responseText ? JSON.parse(xhr.responseText) : undefined;
      } catch {
        parsed = false;
      }
      const ok = xhr.status >= 200 && xhr.status < 300;
      if (!ok) reject(new Error(errorMessage(xhr.status, xhr.statusText, json)));
      else if (!parsed) reject(new SyntaxError("Unexpected response from the server."));
      else resolve((xhr.status === 204 ? undefined : json) as T);
    };
    xhr.send(body);
  });
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

  /** `onUploadProgress` (0..1) reports the upload; the conversion itself runs after it reaches 1. */
  convert: (params: { plantType: PlantType; plantId: number | null; file: File;
                      onUploadProgress?: (fraction: number) => void }) => {
    const form = new FormData();
    form.append("plant_type", params.plantType);
    if (params.plantId) form.append("plant_id", String(params.plantId));
    form.append("file", params.file);
    return params.onUploadProgress
      ? upload<Job>("/api/jobs", form, params.onUploadProgress)
      : request<Job>("/api/jobs", { method: "POST", body: form });
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
