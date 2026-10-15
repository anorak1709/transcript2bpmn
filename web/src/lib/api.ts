import type {
  ApiKey,
  AuditEntry,
  ChatResult,
  Conflict,
  Job,
  MapVersion,
  ProcessMap,
  Project,
  Transcript,
  Usage,
} from "@/lib/types"

const KEY_STORAGE = "t2b_api_key"

// The key lives in this browser only. Storage can be unavailable (private mode, blocked
// site data), so every access is guarded and the app still works for the session.
let memoryKey: string | null = null

export function getApiKey(): string | null {
  try {
    return localStorage.getItem(KEY_STORAGE) ?? memoryKey
  } catch {
    return memoryKey
  }
}

export function setApiKey(key: string | null): void {
  memoryKey = key
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key)
    else localStorage.removeItem(KEY_STORAGE)
  } catch {
    /* session-only */
  }
  window.dispatchEvent(new Event("t2b:auth"))
}

/** Check a key without storing it (sign-in): true if the API accepts it. */
export async function verifyKey(key: string): Promise<boolean> {
  const res = await fetch("/usage", { headers: { Authorization: `Bearer ${key}` } })
  if (res.status === 401) return false
  if (!res.ok) throw new Error(`The server isn't responding properly (${res.status}). Try again shortly.`)
  return true
}

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function detail(data: unknown, status: number): string {
  const d = (data as { detail?: unknown } | null)?.detail
  if (typeof d === "string") return d
  if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? "Invalid request").join("; ")
  return `Request failed (${status})`
}

async function request<T>(
  method: string,
  path: string,
  body?: BodyInit,
  contentType?: string,
  version?: number,
): Promise<T> {
  const headers: Record<string, string> = {}
  // Optimistic concurrency: the server refuses (412) if the map moved past this version.
  if (version != null) headers["If-Match"] = `"${version}"`
  const key = getApiKey()
  if (key) headers.Authorization = `Bearer ${key}`
  if (contentType) headers["Content-Type"] = contentType
  const res = await fetch(path, { method, headers, body })
  if (res.status === 401) {
    setApiKey(null) // sends the user back to sign-in
    throw new ApiError(401, "Your API key is missing or no longer valid.")
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, detail(data, res.status))
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const json = (value: unknown) => JSON.stringify(value)

export const api = {
  // auth check: cheapest authenticated call
  usage: () => request<Usage>("GET", "/usage"),

  projects: () => request<Project[]>("GET", "/projects"),
  project: (id: string) => request<Project>("GET", `/projects/${id}`),
  createProject: (name: string, retentionDays: number | null) =>
    request<Project>("POST", "/projects", json({ name, retention_days: retentionDays }), "application/json"),
  deleteProject: (id: string) => request<Record<string, number>>("DELETE", `/projects/${id}`),

  upload: (projectId: string, file: File) => {
    const form = new FormData()
    form.append("file", file)
    return request<Transcript>("POST", `/projects/${projectId}/transcripts`, form)
  },
  process: (transcriptId: string) => request<Job>("POST", `/transcripts/${transcriptId}/process`),

  conflicts: (projectId: string, status?: "open" | "resolved") =>
    request<Conflict[]>("GET", `/projects/${projectId}/conflicts${status ? `?status=${status}` : ""}`),
  resolveConflict: (id: string, option: number | null, mapVersion?: number) =>
    request<Conflict>("POST", `/conflicts/${id}/resolve`, json({ option }), "application/json", mapVersion),

  map: (id: string) => request<ProcessMap>("GET", `/maps/${id}`),
  chat: (id: string, instruction: string, version: number) =>
    request<ChatResult>("POST", `/maps/${id}/chat`, json({ instruction }), "application/json", version),
  undo: (id: string, version: number) => request<ProcessMap>("POST", `/maps/${id}/undo`, undefined, undefined, version),
  saveBpmn: (id: string, xml: string, version: number) =>
    request<ProcessMap>("PUT", `/maps/${id}/bpmn`, xml, "application/xml", version),
  versions: (id: string) => request<MapVersion[]>("GET", `/maps/${id}/versions`),

  keys: () => request<ApiKey[]>("GET", "/keys"),
  createKey: (name: string) => request<ApiKey & { key: string }>("POST", "/keys", json({ name }), "application/json"),
  revokeKey: (id: string) => request<ApiKey>("DELETE", `/keys/${id}`),
  audit: (limit = 100) => request<AuditEntry[]>("GET", `/audit?limit=${limit}`),
}

/** Download an export with the API key attached (a plain link can't send the header). */
export async function downloadExport(mapId: string, format: "bpmn" | "svg" | "png" | "md"): Promise<void> {
  const key = getApiKey()
  const res = await fetch(`/maps/${mapId}/export/${format}`, {
    headers: key ? { Authorization: `Bearer ${key}` } : {},
  })
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, detail(data, res.status))
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? `process.${format}`
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement("a")
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Someone else changed the map since this client loaded it. */
export const isStale = (e: unknown) => e instanceof ApiError && e.status === 412

/** Save a file the user made locally (e.g. their unsaved diagram before reloading). */
export function downloadText(text: string, filename: string, type = "application/xml"): void {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
