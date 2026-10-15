import type { JobStatus } from "@/lib/types"

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return ""
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m ? `${m}m ${s.toString().padStart(2, "0")}s` : `${s}s`
}

export function formatTimestamp(seconds: number | null | undefined): string {
  if (seconds == null) return ""
  return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return ""
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
}

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued",
  transcribing: "Transcribing audio",
  normalizing: "Cleaning transcript",
  extracting: "Extracting process",
  converting: "Building diagram",
  merging: "Merging into project map",
  done: "Done",
  failed: "Failed",
}

export const AUDIO_EXTENSIONS = [".mp3", ".m4a", ".wav", ".webm", ".mp4"]
export const TEXT_EXTENSIONS = [".vtt", ".srt", ".txt", ".docx"]
export const ACCEPTED_UPLOADS = [...TEXT_EXTENSIONS, ...AUDIO_EXTENSIONS].join(",")
