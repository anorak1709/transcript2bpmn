import { AlertCircle, CheckCircle2, Clock, Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { STATUS_LABEL } from "@/lib/format"
import type { Job } from "@/lib/types"

export function JobBadge({ job, expired }: { job: Job | null; expired?: boolean }) {
  if (expired) return <Badge variant="outline">Content expired</Badge>
  if (!job) {
    return (
      <Badge variant="outline">
        <Clock aria-hidden /> Not processed
      </Badge>
    )
  }
  if (job.status === "done") {
    return (
      <Badge variant="secondary">
        <CheckCircle2 aria-hidden className="text-emerald-600 dark:text-emerald-400" /> Done
      </Badge>
    )
  }
  if (job.status === "failed") {
    return (
      <Badge variant="destructive" title={job.error ?? undefined}>
        <AlertCircle aria-hidden /> Failed
      </Badge>
    )
  }
  return (
    <Badge variant="outline" aria-live="polite">
      <Loader2 aria-hidden className="animate-spin" /> {STATUS_LABEL[job.status]}
    </Badge>
  )
}
