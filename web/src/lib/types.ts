// Mirrors of the API's response models (app/api/*.py). Keep in sync when those change.

export type JobStatus =
  "queued" | "transcribing" | "normalizing" | "extracting" | "converting" | "merging" | "done" | "failed"

export interface Job {
  id: string
  transcript_id: string
  status: JobStatus
  error: string | null
  map_id: string | null
}

export interface Transcript {
  id: string
  project_id: string
  filename: string
  segment_count: number | null
  duration_seconds: number | null
  content_expired: boolean
  created_at: string | null
  latest_job: Job | null
}

export interface Project {
  id: string
  name: string
  retention_days: number | null
  merged_map_id: string | null
  map_version: number | null
  revised_at: string | null
  open_conflicts: number
  transcripts: Transcript[]
}

export type ConflictKind = "owner" | "order" | "condition" | "sequence"

export interface Conflict {
  id: string
  kind: ConflictKind
  description: string
  options: string[]
  node_ids: string[]
  sources: { from: string; segment_ids: string[] }[]
  status: "open" | "resolved"
  resolution: string | null
}

export type NodeType =
  "start_event" | "end_event" | "user_task" | "service_task" | "exclusive_gateway" | "parallel_gateway"

export interface ProcessNode {
  id: string
  type: NodeType
  name: string
  lane_id: string
  source_segment_ids: string[]
  confidence: number
  user_added: boolean
}

export interface OpenQuestion {
  id: string
  question: string
  related_node_ids: string[]
  source_segment_ids: string[]
}

export interface ProcessModel {
  name: string
  lanes: { id: string; name: string }[]
  nodes: ProcessNode[]
  flows: { id: string; source_id: string; target_id: string; condition: string | null }[]
  open_questions: OpenQuestion[]
}

export interface Segment {
  segment_id: string
  speaker: string | null
  start_ts: number | null
  text: string
}

export interface ValidationIssue {
  code: string
  message: string
  node_ids: string[]
}

export interface ProcessMap {
  id: string
  project_id: string
  transcript_id: string | null
  version: number
  can_undo: boolean
  model: ProcessModel
  bpmn_xml: string
  errors: ValidationIssue[]
  segments: Segment[]
  diarization_available: boolean | null
  conflicts: { id: string; kind: ConflictKind; options: string[] }[]
}

export interface ChatResult extends ProcessMap {
  reply: string
  ops: Record<string, unknown>[]
}

export interface MapVersion {
  version: number
  source: "extract" | "chat" | "visual" | "merge" | "resolve"
  instruction: string | null
  created_at: string
}

export interface ApiKey {
  id: string
  name: string
  prefix: string
  created_at: string
  revoked_at: string | null
  current: boolean
}

export interface Usage {
  jobs_this_month: number
  monthly_jobs_quota: number | null
  rate_limit_per_minute: number
  rate_limit_heavy_per_minute: number
}

export interface AuditEntry {
  action: string
  target_type: string
  target_id: string
  api_key_id: string | null
  details: Record<string, unknown>
  created_at: string
}

export const ACTIVE_STATUSES: JobStatus[] = [
  "queued",
  "transcribing",
  "normalizing",
  "extracting",
  "converting",
  "merging",
]

export const isActive = (job: Job | null) => !!job && ACTIVE_STATUSES.includes(job.status)
