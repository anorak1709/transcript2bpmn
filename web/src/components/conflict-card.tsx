import { ChevronRight, Crown, GitBranch } from "lucide-react"
import { useState } from "react"

import { ItemId, Quote } from "@/components/kit"
import { ITEM } from "@/lib/items"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { Conflict, Resolution, Side } from "@/lib/types"
import { cn } from "@/lib/utils"

const KIND_LABEL: Record<Conflict["kind"], string> = {
  owner: "Who does it",
  order: "Order of steps",
  condition: "Condition",
  sequence: "What follows",
  missing_step: "In the policy, not in meetings",
  unofficial_step: "In meetings, not in the policy",
}

type PointConflict = Pick<Conflict, "kind" | "description" | "options"> &
  Partial<Pick<Conflict, "origin" | "sides" | "owner_side">>

/** Who said what on each side. The process owner's side is marked, never preferred. */
function Evidence({ sides, ownerSide }: { sides: Side[]; ownerSide: number | null }) {
  const shown = sides.filter((s) => s.quotes.length)
  if (!shown.length) return null
  return (
    <details className="group/ev">
      <summary className="flex min-h-6 flex-wrap items-center gap-x-1 text-sm text-fg-muted select-none hover:text-fg [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 transition-transform group-open/ev:rotate-90" aria-hidden />
        Who said what
        {ownerSide != null && (
          <span className="inline-flex items-center gap-1 text-warn sm:ml-1">
            <Crown className="size-3.5" aria-hidden /> Process owner says {sides[ownerSide].label}
          </span>
        )}
      </summary>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        {sides.map((s, i) =>
          s.quotes.length ? (
            <div key={i} className="rounded-md border border-line bg-app/60 p-3">
              <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-fg-muted">
                {s.label}
                {i === ownerSide && (
                  <span className="inline-flex items-center gap-1 text-warn">
                    · <Crown className="size-3" aria-hidden /> process owner
                  </span>
                )}
              </p>
              <div className="space-y-2.5">
                {s.quotes.map((q, k) => (
                  <Quote key={k} q={q} />
                ))}
              </div>
            </div>
          ) : null,
        )}
      </div>
    </details>
  )
}

/** "Both are true": name what decides it, then label each option. */
function VariantForm({
  options,
  onSubmit,
  onCancel,
}: {
  options: string[]
  onSubmit: (question: string, labels: string[]) => Promise<void>
  onCancel: () => void
}) {
  const [question, setQuestion] = useState("")
  const [labels, setLabels] = useState(options.map(() => ""))
  const [busy, setBusy] = useState(false)
  const ready =
    question.trim() && labels.every((l) => l.trim()) && new Set(labels.map((l) => l.trim())).size === labels.length
  return (
    <form
      className="space-y-3 rounded-md border border-line bg-app/60 p-3"
      onSubmit={async (e) => {
        e.preventDefault()
        if (!ready) return
        setBusy(true)
        try {
          await onSubmit(
            question.trim(),
            labels.map((l) => l.trim()),
          )
        } finally {
          setBusy(false)
        }
      }}
    >
      <p className="text-sm text-fg-muted">
        Keep every version as a branch of a new decision, e.g. <i>Which region?</i> → North / South.
      </p>
      <div className="space-y-1.5">
        <label className="eyebrow block" htmlFor="variant-question">
          What decides it?
        </label>
        <Input
          id="variant-question"
          value={question}
          maxLength={200}
          placeholder="e.g. Which region? / Supplier size?"
          onChange={(e) => setQuestion(e.target.value)}
          autoFocus
        />
      </div>
      {options.map((opt, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-center gap-2">
          <label htmlFor={`variant-label-${i}`} className="truncate text-sm text-fg-muted" title={opt}>
            When it's <span className="font-medium text-fg">{opt}</span>
          </label>
          <Input
            id={`variant-label-${i}`}
            value={labels[i]}
            placeholder={i === 0 ? "e.g. North" : "e.g. South"}
            onChange={(e) => setLabels(labels.map((l, k) => (k === i ? e.target.value : l)))}
          />
        </div>
      ))}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!ready || busy}>
          {busy ? "Applying…" : "Keep both"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function Card({ id, children, className }: { id: string; children: React.ReactNode; className?: string }) {
  return (
    <article
      id={id}
      className={cn("scroll-mt-24 rounded-lg border border-line bg-panel p-4 target:border-brand/60", className)}
    >
      {children}
    </article>
  )
}

/** A disagreement between meetings, with its short id (D1…) shown here and on the diagram.
 *  Nothing is applied until someone chooses. */
export function ConflictPoint({
  itemId: id,
  conflict,
  onResolve,
  onSelect,
  compact,
}: {
  itemId: string
  conflict: PointConflict
  onResolve: (how: Resolution) => Promise<void>
  onSelect?: () => void
  compact?: boolean
}) {
  const { kind, description, options } = conflict
  const [busy, setBusy] = useState<number | "manual" | null>(null)
  const [variant, setVariant] = useState(false)
  const resolve = async (how: Resolution, key: number | "manual") => {
    setBusy(key)
    try {
      await onResolve(how)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card id={id} className={compact ? "border-0 bg-transparent p-0" : undefined}>
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <ItemId id={id} tone={ITEM.disagreement.tone} />
          <span className="text-xs font-medium text-fg-muted">
            <span className="sr-only">Disagreement {id}: </span>
            {KIND_LABEL[kind]}
          </span>
        </div>
        {onSelect ? (
          <button
            type="button"
            onClick={onSelect}
            className="text-left text-[0.95rem] leading-relaxed hover:underline hover:decoration-fg-subtle hover:underline-offset-4"
          >
            {description}
          </button>
        ) : (
          <p className="text-[0.95rem] leading-relaxed">{description}</p>
        )}
        {conflict.sides && <Evidence sides={conflict.sides} ownerSide={conflict.owner_side ?? null} />}
        {variant ? (
          <VariantForm
            options={options}
            onCancel={() => setVariant(false)}
            onSubmit={(question, labels) => resolve({ variant: { question, labels } }, "manual")}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Settle ${id}`}>
            <span className="text-xs text-fg-subtle">Settle as</span>
            {options.map((opt, i) => (
              <Button
                key={i}
                size="sm"
                variant="outline"
                disabled={busy !== null}
                aria-label={`Settle as ${opt}`}
                onClick={() => resolve({ option: i }, i)}
              >
                {busy === i ? "Applying…" : opt}
              </Button>
            ))}
            {kind !== "order" && (
              <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => setVariant(true)}>
                <GitBranch aria-hidden /> Both, by case…
              </Button>
            )}
            <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => resolve({}, "manual")}>
              {busy === "manual" ? "Saving…" : "I fixed it myself"}
            </Button>
          </div>
        )}
      </div>
    </Card>
  )
}

/** Where what people said differs from the written policy (P1…). */
export function PolicyDifference({
  itemId: id,
  conflict,
  onResolve,
}: {
  itemId: string
  conflict: Conflict
  onResolve: (how: Resolution) => Promise<void>
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const act = async (how: Resolution, key: string) => {
    setBusy(key)
    try {
      await onResolve(how)
    } finally {
      setBusy(null)
    }
  }
  const policySays = conflict.options[1]
  return (
    <Card id={id}>
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <ItemId id={id} tone={ITEM.policy.tone} />
          <span className="text-xs font-medium text-fg-muted">
            <span className="sr-only">Policy difference {id}: </span>
            {KIND_LABEL[conflict.kind]}
          </span>
        </div>
        <p className="text-[0.95rem] leading-relaxed">{conflict.description}</p>
        <Evidence
          sides={conflict.sides.map((s, i) => ({
            ...s,
            label: conflict.sides.length === 2 ? (i === 0 ? "The meetings" : "The policy") : s.label,
          }))}
          ownerSide={null}
        />
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Settle ${id}`}>
          {policySays && (
            <Button size="sm" variant="outline" disabled={!!busy} onClick={() => act({ option: 1 }, "policy")}>
              {busy === "policy" ? "Applying…" : `Change the map to “${policySays}”`}
            </Button>
          )}
          <Button size="sm" variant="outline" disabled={!!busy} onClick={() => act({ note: "deviation" }, "deviation")}>
            {busy === "deviation" ? "Saving…" : "Note as a deviation"}
          </Button>
          <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => act({ note: "dismissed" }, "dismissed")}>
            {busy === "dismissed" ? "Saving…" : "Dismiss"}
          </Button>
        </div>
      </div>
    </Card>
  )
}
