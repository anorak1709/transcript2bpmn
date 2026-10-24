import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { formatTimestamp, ROLE_LABEL } from "@/lib/format"
import type { Conflict, Resolution, Side } from "@/lib/types"
import { cn } from "@/lib/utils"

const KIND_LABEL: Record<Conflict["kind"], string> = {
  owner: "Who does it",
  order: "Order of steps",
  condition: "Condition",
  sequence: "What follows",
  missing_step: "In the policy, not in the meetings",
  unofficial_step: "In the meetings, not in the policy",
}

type PointConflict = Pick<Conflict, "kind" | "description" | "options"> &
  Partial<Pick<Conflict, "origin" | "sides" | "owner_side">>

/** Who said what on each side, footnote-style. The process owner's side is marked, not
 *  preferred: the reader still decides. */
function Evidence({ sides, ownerSide }: { sides: Side[]; ownerSide: number | null }) {
  const shown = sides.filter((s) => s.quotes.length)
  if (!shown.length) return null
  return (
    <details className="group text-sm">
      <summary className="cursor-pointer text-fg-muted select-none hover:text-fg">
        Who said what
        {ownerSide != null && (
          <span className="font-bold text-fg"> · the process owner says {sides[ownerSide].label}</span>
        )}
      </summary>
      <div className="mt-2 space-y-3 border-l border-line-strong pl-3">
        {sides.map((s, i) =>
          s.quotes.length ? (
            <div key={i}>
              <p className="label">
                {s.label}
                {i === ownerSide && <span className="text-fg"> · process owner</span>}
              </p>
              <ul className="mt-1 space-y-1.5">
                {s.quotes.map((q, k) => (
                  <li key={k}>
                    <span className="text-[0.98rem]">
                      {q.text ? `“${q.text}”` : "Source text no longer available."}
                    </span>
                    <span className="ml-1.5 text-xs text-fg-muted">
                      {q.policy
                        ? `policy · ${q.meeting}`
                        : [
                            q.speaker ?? "unknown speaker",
                            q.role && ROLE_LABEL[q.role],
                            q.start_ts != null && formatTimestamp(q.start_ts),
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
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
      className="space-y-3 rounded-sm border border-line-strong bg-surface p-3"
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
        <label className="label block" htmlFor="variant-question">
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
          <label htmlFor={`variant-label-${i}`} className="truncate text-sm" title={opt}>
            When it's <b>{opt}</b>
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

/** The explanation after a description's leading question (the question is shown above it). */
function afterQuestion(description: string): string {
  return description.replace(/^.+?\?\s+(?=(?:The|Existing|Policy|Meetings|They)\b)/, "")
}

/** A point of disagreement between meetings, numbered like a clause (i., ii., …). The
 *  options are what each meeting said; nothing is applied until someone chooses. */
export function ConflictPoint({
  number,
  conflict,
  onResolve,
  onSelect,
  className,
  bare,
}: {
  number: number
  conflict: PointConflict
  onResolve: (how: Resolution) => Promise<void>
  onSelect?: () => void
  className?: string
  bare?: boolean // inside an opened review item: the row above already shows the question
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
    <article className={cn(bare ? "py-1" : "grid grid-cols-[2rem_1fr] gap-x-2 py-4", className)}>
      {!bare && (
        <span className="tabular pt-0.5 text-xl leading-none text-signal" aria-hidden>
          {number}.
        </span>
      )}
      <div className="min-w-0 space-y-3">
        {!bare && (
          <h3 className="label">
            <span className="sr-only">Point {number}: </span>
            {KIND_LABEL[kind]}
          </h3>
        )}
        {bare ? (
          <p className="text-fg-muted">{afterQuestion(description)}</p>
        ) : onSelect ? (
          <button
            type="button"
            onClick={onSelect}
            className="text-left text-[1.08rem] leading-snug hover:underline hover:decoration-1 hover:underline-offset-4"
          >
            {description}
          </button>
        ) : (
          <p className="text-[1.08rem] leading-snug">{description}</p>
        )}
        {conflict.sides && <Evidence sides={conflict.sides} ownerSide={conflict.owner_side ?? null} />}
        {variant ? (
          <VariantForm
            options={options}
            onCancel={() => setVariant(false)}
            onSubmit={(question, labels) => resolve({ variant: { question, labels } }, "manual")}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-2 pt-1" role="group" aria-label={`Settle point ${number}`}>
            <span className="label">Settle as &gt;&gt;</span>
            {options.map((opt, i) => (
              <Button
                key={i}
                size={bare ? "default" : "sm"}
                variant="outline"
                disabled={busy !== null}
                aria-label={`Settle as ${opt}`}
                onClick={() => resolve({ option: i }, i)}
              >
                {busy === i ? "Applying…" : opt}
              </Button>
            ))}
            {kind !== "order" && (
              <Button
                size={bare ? "default" : "sm"}
                variant="ghost"
                disabled={busy !== null}
                onClick={() => setVariant(true)}
              >
                Both, by case…
              </Button>
            )}
            <Button
              size={bare ? "default" : "sm"}
              variant="ghost"
              className="text-fg-muted"
              disabled={busy !== null}
              onClick={() => resolve({}, "manual")}
            >
              {busy === "manual" ? "Saving…" : "I fixed it myself"}
            </Button>
          </div>
        )}
      </div>
    </article>
  )
}

/** Where what people said differs from the written policy. Numbered §1, §2 … so they're never
 *  confused with points of disagreement between meetings. */
export function PolicyDifference({
  number,
  conflict,
  onResolve,
  bare,
}: {
  number: number
  conflict: Conflict
  onResolve: (how: Resolution) => Promise<void>
  bare?: boolean
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
    <article className={bare ? "py-1" : "grid grid-cols-[2rem_1fr] gap-x-2 py-4"}>
      {!bare && (
        <span className="tabular pt-0.5 text-lg leading-none text-signal" aria-hidden>
          §{number}
        </span>
      )}
      <div className="min-w-0 space-y-3">
        {!bare && (
          <h3 className="label">
            <span className="sr-only">Policy difference {number}: </span>
            {KIND_LABEL[conflict.kind]}
          </h3>
        )}
        <p className={bare ? "text-fg-muted" : "text-[1.08rem] leading-snug"}>
          {bare ? afterQuestion(conflict.description) : conflict.description}
        </p>
        <Evidence
          sides={conflict.sides.map((s, i) => ({
            ...s,
            label: conflict.sides.length === 2 ? (i === 0 ? "The meetings" : "The policy") : s.label,
          }))}
          ownerSide={null}
        />
        <div
          className="flex flex-wrap items-center gap-2 pt-1"
          role="group"
          aria-label={`Settle policy difference ${number}`}
        >
          {policySays && (
            <Button size="sm" variant="outline" disabled={!!busy} onClick={() => act({ option: 1 }, "policy")}>
              {busy === "policy" ? "Applying…" : `Change the map to “${policySays}”`}
            </Button>
          )}
          <Button size="sm" variant="outline" disabled={!!busy} onClick={() => act({ note: "deviation" }, "deviation")}>
            {busy === "deviation" ? "Saving…" : "Note as a deviation"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-fg-muted"
            disabled={!!busy}
            onClick={() => act({ note: "dismissed" }, "dismissed")}
          >
            {busy === "dismissed" ? "Saving…" : "Dismiss"}
          </Button>
        </div>
      </div>
    </article>
  )
}
