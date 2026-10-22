// Mirrors of the API's response models (app/api/*.py). Keep in sync when those change.

export type JobStatus =
  "queued" | "transcribing" | "normalizing" | "extracting" | "converting" | "merging" | "comparing" | "done" | "failed"

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
  purpose: "meeting" | "policy"
  live_status: "recording" | "finished" | null
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
  open_policy_differences: number
  open_gaps: number
  transcripts: Transcript[]
}

export type ConflictKind = "owner" | "order" | "condition" | "sequence" | "missing_step" | "unofficial_step"
export type SpeakerRole = "owner" | "performer" | "observer"

export interface Quote {
  text: string | null // null: deleted by the retention policy
  speaker: string | null
  role: SpeakerRole | null
  meeting: string
  start_ts: number | null
  policy: boolean
}

export interface Side {
  label: string
  quotes: Quote[]
}

export interface Conflict {
  id: string
  origin: "meeting" | "policy"
  kind: ConflictKind
  description: string
  options: string[]
  node_ids: string[]
  sources: { from: string; segment_ids: string[] }[]
  sides: Side[]
  owner_side: number | null // the side the process owner backs, if only one does
  status: "open" | "resolved"
  resolution: string | null
}

/** How to settle: pick an option, keep both as variants, note a policy deviation, or (empty)
 *  "I fixed it myself". */
export type Resolution =
  | { option: number }
  | { variant: { question: string; labels: string[] } }
  | { note: "deviation" | "dismissed" }
  | Record<string, never>

export interface Speaker {
  name: string
  role: SpeakerRole | null
  lines: number
  meetings: number
}

export interface Gap {
  id: string
  kind: "one_outcome" | "no_owner" | "dead_end" | "no_trigger" | "no_exception"
  node_ids: string[]
  description: string
  question: string
}

export type SignoffStatus = "pending" | "approved" | "changes_requested" | "revoked" | "expired"

export interface Signoff {
  id: string
  name: string
  lanes: string[]
  lane_ids: string[]
  status: SignoffStatus
  comment: string | null
  requested_version: number
  decided_version: number | null
  current_version: number | null
  created_at: string | null
  decided_at: string | null
  expires_at: string
  token: string | null // only right after creating it
}

export interface ReviewStep {
  id: string
  kind: "task" | "decision"
  name: string
  lane: string
  comes_from: { name: string; lane: string; condition: string | null }[]
  goes_to: { name: string; lane: string; condition: string | null }[]
  quotes: Quote[]
}

export interface Review {
  process: string
  name: string
  lanes: string[]
  version: number
  requested_version: number
  steps: ReviewStep[]
  decision: "approved" | "changes_requested" | null
  comment: string | null
  decided_version: number | null
  decided_at: string | null
  expires_at: string
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
  "comparing",
]

export const isActive = (job: Job | null) => !!job && ACTIVE_STATUSES.includes(job.status)

export interface ReviewItem {
  node_id: string
  name: string
  type: string
  lane: string
  confidence: number
  cited: boolean
  reason: string | null // why it needs a look; null = no flag
  reviewed: boolean
}

export interface Suggestion {
  id: string
  kind: "automate" | "handoff" | "approvals" | "ai"
  title: string
  detail: string
  node_ids: string[]
}

export interface Session {
  key: string
  email: string
  workspace_id: string
  workspace_name: string
}

export interface WorkspaceRef {
  id: string
  name: string
  role: string
}

export interface Me {
  email: string | null
  workspace: WorkspaceRef
  workspaces: WorkspaceRef[]
  sandbox: boolean
}

export interface Member {
  email: string
  role: string
  joined_at: string | null
}

export interface Invite {
  id: string
  email: string
  created_at: string | null
  accepted_at: string | null
}

export interface Workspace {
  id: string
  name: string
  share_corrections: "off" | "anonymised" | "full"
  sandbox_expires_at: string | null
}

export interface CorrectionsSummary {
  total: number
  by_kind: Record<string, number>
}

export interface ElementEvidence {
  meetings: number
  with_timers: number
  with_subprocesses: number
}

export interface Integrations {
  camunda: boolean
  ai: boolean
}

export interface DemoStatus {
  sandboxes: boolean
  demo_mode: boolean
  sandbox_hours: number
}

export interface Live {
  transcript_id: string
  status: "recording" | "finished" | null
  chunk_seconds: number
  lines: Segment[]
  map_id: string | null
  map_version: number | null
}
