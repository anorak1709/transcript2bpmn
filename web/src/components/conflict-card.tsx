import { useState } from "react"

import { Button } from "@/components/ui/button"
import { roman } from "@/lib/format"
import { cn } from "@/lib/utils"

const KIND_LABEL = {
  owner: "Who does it",
  order: "Order of steps",
  condition: "Condition",
  sequence: "What follows",
} as const

/** A point of disagreement between meetings, numbered like a clause (i., ii., …). The
 *  options are what each meeting said; nothing is applied until someone chooses. */
export function ConflictPoint({
  number,
  kind,
  description,
  options,
  onResolve,
  onSelect,
  className,
}: {
  number: number
  kind: keyof typeof KIND_LABEL
  description: string
  options: string[]
  onResolve: (option: number | null) => Promise<void>
  onSelect?: () => void
  className?: string
}) {
  const [busy, setBusy] = useState<number | "manual" | null>(null)
  const resolve = async (option: number | null) => {
    setBusy(option ?? "manual")
    try {
      await onResolve(option)
    } finally {
      setBusy(null)
    }
  }

  return (
    <article className={cn("grid grid-cols-[2rem_1fr] gap-x-2 py-4", className)}>
      <span className="serif tabular pt-0.5 text-xl leading-none text-oxblood" aria-hidden>
        {roman(number)}.
      </span>
      <div className="min-w-0 space-y-2">
        <h3 className="label font-sans">
          <span className="sr-only">Point {roman(number)}: </span>
          {KIND_LABEL[kind]}
        </h3>
        {onSelect ? (
          <button
            type="button"
            onClick={onSelect}
            className="serif text-left text-[1.08rem] leading-snug hover:underline hover:decoration-1 hover:underline-offset-4"
          >
            {description}
          </button>
        ) : (
          <p className="serif text-[1.08rem] leading-snug">{description}</p>
        )}
        <div
          className="flex flex-wrap items-center gap-2 pt-1"
          role="group"
          aria-label={`Settle point ${roman(number)}`}
        >
          <span className="text-xs text-graphite">Settle as</span>
          {options.map((opt, i) => (
            <Button
              key={i}
              size="sm"
              variant="outline"
              disabled={busy !== null}
              aria-label={`Settle as ${opt}`}
              onClick={() => resolve(i)}
            >
              {busy === i ? "Applying…" : opt}
            </Button>
          ))}
          <Button
            size="sm"
            variant="ghost"
            className="text-graphite"
            disabled={busy !== null}
            onClick={() => resolve(null)}
          >
            {busy === "manual" ? "Saving…" : "I fixed it myself"}
          </Button>
        </div>
      </div>
    </article>
  )
}
