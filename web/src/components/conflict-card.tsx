import { GitCompareArrows, Loader2 } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

const KIND_LABEL = {
  owner: "Who does it",
  order: "Order of steps",
  condition: "Decision condition",
  sequence: "What comes next",
} as const

/** One disagreement between meetings, with a button per option plus "I fixed it myself". */
export function ConflictCard({
  kind,
  description,
  options,
  onResolve,
  onSelect,
}: {
  kind: keyof typeof KIND_LABEL
  description: string
  options: string[]
  onResolve: (option: number | null) => Promise<void>
  onSelect?: () => void
}) {
  const [busy, setBusy] = useState<number | "manual" | null>(null)

  async function resolve(option: number | null) {
    setBusy(option ?? "manual")
    try {
      await onResolve(option)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-3 rounded-lg border bg-card p-3 text-sm">
      <div className="flex items-start gap-2">
        <GitCompareArrows className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
        <div className="min-w-0 space-y-1">
          <Badge variant="outline">{KIND_LABEL[kind]}</Badge>
          {onSelect ? (
            <button type="button" onClick={onSelect} className="block text-left hover:underline">
              {description}
            </button>
          ) : (
            <p>{description}</p>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Resolve this conflict">
        {options.map((opt, i) => (
          <Button key={i} size="sm" variant="outline" disabled={busy !== null} onClick={() => resolve(i)}>
            {busy === i && <Loader2 className="animate-spin" aria-hidden />}
            Use: {opt}
          </Button>
        ))}
        <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => resolve(null)}>
          {busy === "manual" && <Loader2 className="animate-spin" aria-hidden />}I fixed it myself
        </Button>
      </div>
    </div>
  )
}
