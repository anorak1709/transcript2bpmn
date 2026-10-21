import type {
  ApiKey,
  AuditEntry,
  ChatResult,
  Conflict,
  CorrectionsSummary,
  DemoStatus,
  ElementEvidence,
  Integrations,
  Invite,
  Live,
  Me,
  Member,
  ReviewItem,
  Session,
  Suggestion,
  Workspace,
  Gap,
  Job,
  MapVersion,
  ProcessMap,
  Project,
  Resolution,
  Review,
  Signoff,
  Speaker,
  SpeakerRole,
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

  upload: (projectId: string, file: File, purpose: "meeting" | "policy" = "meeting") => {
    const form = new FormData()
    form.append("file", file)
    return request<Transcript>("POST", `/projects/${projectId}/transcripts?purpose=${purpose}`, form)
  },
  process: (transcriptId: string) => request<Job>("POST", `/transcripts/${transcriptId}/process`),

  conflicts: (projectId: string, filter: { status?: "open" | "resolved"; origin?: "meeting" | "policy" } = {}) =>
    request<Conflict[]>("GET", `/projects/${projectId}/conflicts?${new URLSearchParams(filter)}`),
  resolveConflict: (id: string, how: Resolution, mapVersion?: number) =>
    request<Conflict>("POST", `/conflicts/${id}/resolve`, json(how), "application/json", mapVersion),

  speakers: (projectId: string) => request<Speaker[]>("GET", `/projects/${projectId}/speakers`),
  setSpeakerRole: (projectId: string, name: string, role: SpeakerRole | null) =>
    request<Speaker>(
      "PUT",
      `/projects/${projectId}/speakers/${encodeURIComponent(name)}`,
      json({ role }),
      "application/json",
    ),
  gaps: (projectId: string) => request<Gap[]>("GET", `/projects/${projectId}/gaps`),
  dismissGap: (projectId: string, gapId: string) => request("POST", `/projects/${projectId}/gaps/${gapId}/dismiss`),

  signoffs: (projectId: string) => request<Signoff[]>("GET", `/projects/${projectId}/signoffs`),
  requestSignoff: (projectId: string, name: string, laneIds: string[]) =>
    request<Signoff>("POST", `/projects/${projectId}/signoffs`, json({ name, lane_ids: laneIds }), "application/json"),
  revokeSignoff: (id: string) => request<Signoff>("DELETE", `/signoffs/${id}`),

  map: (id: string) => request<ProcessMap>("GET", `/maps/${id}`),
  chat: (id: string, instruction: string, version: number) =>
    request<ChatResult>("POST", `/maps/${id}/chat`, json({ instruction }), "application/json", version),
  undo: (id: string, version: number) => request<ProcessMap>("POST", `/maps/${id}/undo`, undefined, undefined, version),
  saveBpmn: (id: string, xml: string, version: number) =>
    request<ProcessMap>("PUT", `/maps/${id}/bpmn`, xml, "application/xml", version),
  versions: (id: string) => request<MapVersion[]>("GET", `/maps/${id}/versions`),

  me: () => request<Me>("GET", "/auth/me"),
  switchWorkspace: (workspaceId: string) =>
    request<Session>("POST", "/auth/switch", json({ workspace_id: workspaceId }), "application/json"),
  logout: () => request("POST", "/auth/logout"),
  members: () => request<Member[]>("GET", "/members"),
  invites: () => request<Invite[]>("GET", "/invites"),
  invite: (email: string) => request<Invite>("POST", "/invites", json({ email }), "application/json"),
  cancelInvite: (id: string) => request("DELETE", `/invites/${id}`),
  workspace: () => request<Workspace>("GET", "/workspace"),
  setSharing: (level: Workspace["share_corrections"]) =>
    request<Workspace>("PUT", "/workspace", json({ share_corrections: level }), "application/json"),
  corrections: () => request<CorrectionsSummary>("GET", "/corrections?limit=0"),
  elementEvidence: () => request<ElementEvidence>("GET", "/insights/bpmn-elements"),
  integrations: () => request<Integrations>("GET", "/integrations"),

  reviewQueue: (mapId: string) => request<ReviewItem[]>("GET", `/maps/${mapId}/review`),
  markReviewed: (mapId: string, nodeId: string, checked: boolean) =>
    request("POST", `/maps/${mapId}/review/${encodeURIComponent(nodeId)}`, json({ checked }), "application/json"),
  improvements: (mapId: string) => request<Suggestion[]>("GET", `/maps/${mapId}/improvements`),
  aiImprovements: (mapId: string) => request<Suggestion[]>("POST", `/maps/${mapId}/improvements/ai`),
  pushCamunda: (mapId: string) => request<{ target: string; url: string }>("POST", `/maps/${mapId}/push/camunda`),

  startLive: (projectId: string) => request<Live>("POST", `/projects/${projectId}/live`),
  live: (transcriptId: string) => request<Live>("GET", `/transcripts/${transcriptId}/live`),
  liveChunk: (transcriptId: string, index: number, offset: number, blob: Blob) => {
    const form = new FormData()
    form.append("file", blob, `chunk-${index}.webm`)
    return request<Live>("POST", `/transcripts/${transcriptId}/live/chunks?index=${index}&offset=${offset}`, form)
  },
  finishLive: (transcriptId: string) => request<Job>("POST", `/transcripts/${transcriptId}/live/finish`),

  keys: () => request<ApiKey[]>("GET", "/keys"),
  createKey: (name: string) => request<ApiKey & { key: string }>("POST", "/keys", json({ name }), "application/json"),
  revokeKey: (id: string) => request<ApiKey>("DELETE", `/keys/${id}`),
  audit: (limit = 100) => request<AuditEntry[]>("GET", `/audit?limit=${limit}`),
}

/** Download an export with the API key attached (a plain link can't send the header). */
export function downloadExport(mapId: string, format: "bpmn" | "svg" | "png" | "md" | "docx" | "pdf"): Promise<void> {
  return download(`/maps/${mapId}/export/${format}`, `process.${format}`)
}

/** The next meeting's agenda (Markdown). */
export function downloadAgenda(projectId: string): Promise<void> {
  return download(`/projects/${projectId}/agenda`, "agenda.md")
}

async function download(path: string, fallback: string): Promise<void> {
  const key = getApiKey()
  const res = await fetch(path, {
    headers: key ? { Authorization: `Bearer ${key}` } : {},
  })
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, detail(data, res.status))
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? fallback
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

/** Reviewer side of a sign-off link: no API key (the token is the credential), and a 401/410
 *  must never sign the owner out of their own browser. */
async function reviewRequest<T>(token: string, body?: unknown): Promise<T> {
  const res = await fetch(`/review/${encodeURIComponent(token)}`, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, detail(data, res.status))
  }
  return (await res.json()) as T
}

export const review = {
  get: (token: string) => reviewRequest<Review>(token),
  decide: (token: string, decision: "approved" | "changes_requested", comment: string) =>
    reviewRequest<Review>(token, { decision, comment }),
}

/** Sign-up / sign-in without a key yet: never touches the stored key on errors. */
async function publicRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, detail(data, res.status))
  }
  return (await res.json()) as T
}

export const auth = {
  requestLink: (email: string) => publicRequest<{ status: string }>("POST", "/auth/magic-link", { email }),
  verify: (token: string) => publicRequest<Session>("POST", "/auth/verify", { token }),
  demoStatus: () => publicRequest<DemoStatus>("GET", "/demo/status"),
  sandbox: () => publicRequest<Session>("POST", "/demo/sandbox"),
}
