import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import type { Suggestion } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Steps to check, least certain first: uncited, then low confidence. Checked ones drop to the end. */
export function ReviewQueue({
  mapId,
  limit,
  onSelect,
}: {
  mapId: string
  limit?: number
  onSelect?: (nodeId: string) => void
}) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ["review", mapId], queryFn: () => api.reviewQueue(mapId) })
  const mark = useMutation({
    mutationFn: ({ nodeId, checked }: { nodeId: string; checked: boolean }) => api.markReviewed(mapId, nodeId, checked),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["review", mapId] }),
    onError: (e) => toast.error(e.message),
  })
  if (!q.data) return null
  const open = q.data.filter((i) => !i.reviewed)
  const flagged = open.filter((i) => i.reason)
  const shown = limit ? open.slice(0, limit) : q.data
  if (!q.data.length) return <p className="text-fg-muted">No AI-drafted steps to check.</p>
  return (
    <div>
      <p className="mb-2 text-sm text-fg-muted">
        {flagged.length
          ? `${flagged.length} step${flagged.length === 1 ? "" : "s"} the AI is least sure of, then the rest.`
          : open.length
            ? "Nothing flagged. The remaining steps, least confident first."
            : "Every step has been checked."}{" "}
        {q.data.length - open.length} of {q.data.length} checked.
      </p>
      <ul className="divide-y divide-line">
        {shown.map((i) => (
          <li key={i.node_id} className="flex items-start gap-3 py-2.5">
            <div className="min-w-0 flex-1">
              {onSelect ? (
                <button type="button" onClick={() => onSelect(i.node_id)} className="text-left hover:underline">
                  {i.name}
                </button>
              ) : (
                <span className={cn(i.reviewed && "text-fg-muted")}>{i.name}</span>
              )}
              <span className="block text-sm text-fg-muted">
                {i.lane}
                {i.reason ? (
                  <span className="text-signal"> · {i.reason}</span>
                ) : (
                  ` · ${Math.round(i.confidence * 100)}%`
                )}
              </span>
            </div>
            <Button
              size="sm"
              variant={i.reviewed ? "ghost" : "outline"}
              aria-pressed={i.reviewed}
              disabled={mark.isPending}
              onClick={() => mark.mutate({ nodeId: i.node_id, checked: !i.reviewed })}
            >
              {i.reviewed ? (
                <>
                  <Check aria-hidden /> Checked
                </>
              ) : (
                "Looks right"
              )}
            </Button>
          </li>
        ))}
      </ul>
      {limit && open.length > limit && (
        <p className="mt-2 text-sm text-fg-muted">And {open.length - limit} more in the map editor's Review tab.</p>
      )}
    </div>
  )
}

const KIND_LABEL: Record<Suggestion["kind"], string> = {
  automate: "Automate",
  handoff: "Handoffs",
  approvals: "Approvals",
  ai: "From the AI",
}

/** Where the process could be faster or cheaper: rules from the map, AI ideas only on request. */
export function Improvements({ mapId, aiAvailable }: { mapId: string; aiAvailable: boolean }) {
  const rules = useQuery({ queryKey: ["improvements", mapId], queryFn: () => api.improvements(mapId) })
  const [ai, setAi] = useState<Suggestion[] | null>(null)
  const ask = useMutation({
    mutationFn: () => api.aiImprovements(mapId),
    onSuccess: setAi,
    onError: (e) => toast.error(e.message),
  })
  const all = [...(rules.data ?? []), ...(ai ?? [])]
  return (
    <div>
      {all.length === 0 && rules.data && <p className="text-fg-muted">No obvious improvements from the map's shape.</p>}
      <ul className="divide-y divide-line">
        {all.map((s) => (
          <li key={s.id} className="py-3">
            <p className="label">{KIND_LABEL[s.kind]}</p>
            <p className="text-[1.05rem] leading-snug">{s.title}</p>
            <p className="mt-0.5 text-sm text-fg-muted">{s.detail}</p>
          </li>
        ))}
      </ul>
      {aiAvailable && ai === null && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button size="sm" variant="outline" disabled={ask.isPending} onClick={() => ask.mutate()}>
            {ask.isPending ? "Thinking…" : "Ask AI for more ideas"}
          </Button>
          <span className="text-xs text-fg-muted">Uses AI credits; the ideas above are free.</span>
        </div>
      )}
    </div>
  )
}
