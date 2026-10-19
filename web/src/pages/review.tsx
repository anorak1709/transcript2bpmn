import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, Check, ChevronRight, PenLine, Workflow } from "lucide-react"
import { useState } from "react"
import { useParams } from "react-router"

import { Chip, PageHeader, Panel, Quote } from "@/components/kit"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, review } from "@/lib/api"
import { formatDay } from "@/lib/format"
import type { ReviewStep } from "@/lib/types"

function Step({ step, number }: { step: ReviewStep; number: number }) {
  const label = (n: { name: string; lane: string }) =>
    `${n.name}${n.lane && n.lane !== step.lane ? ` (${n.lane})` : ""}`
  return (
    <li className="rounded-lg border border-line bg-panel p-4">
      <div className="flex items-start gap-3">
        <span className="tabular inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-raised text-xs font-semibold text-fg-muted">
          {number}
        </span>
        <div className="min-w-0 flex-1 space-y-3">
          <div>
            <p className="eyebrow">
              {step.kind === "decision" ? "Decision" : "Step"} · {step.lane}
            </p>
            <h3 className="mt-0.5 text-base">{step.name}</h3>
          </div>
          <dl className="grid gap-1.5 text-sm sm:grid-cols-[7rem_1fr]">
            <dt className="flex items-center gap-1.5 text-fg-muted">
              <ArrowUp className="size-3.5" aria-hidden /> Comes after
            </dt>
            <dd>{step.comes_from.length ? step.comes_from.map(label).join("; ") : "The start of the process"}</dd>
            <dt className="flex items-center gap-1.5 text-fg-muted">
              <ArrowDown className="size-3.5" aria-hidden /> Then
            </dt>
            <dd>
              {step.goes_to.length
                ? step.goes_to.map((n) => `${n.condition ? `if ${n.condition}: ` : ""}${label(n)}`).join("; ")
                : "The process ends"}
            </dd>
          </dl>
          {step.quotes.length > 0 && (
            <details className="group/src">
              <summary className="inline-flex min-h-6 items-center gap-1 text-sm text-fg-muted select-none hover:text-fg [&::-webkit-details-marker]:hidden">
                <ChevronRight className="size-3.5 transition-transform group-open/src:rotate-90" aria-hidden />
                Where this came from
              </summary>
              <ol className="mt-3 space-y-2.5">
                {step.quotes.map((q, i) => (
                  <li key={i}>
                    <Quote q={q} index={i + 1} />
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      </div>
    </li>
  )
}

/** A stakeholder's private review link: only their part of the map, then approve or ask for
 *  changes. No account, no app chrome. */
export function ReviewPage() {
  const { token = "" } = useParams()
  const qc = useQueryClient()
  const [comment, setComment] = useState("")
  const data = useQuery({ queryKey: ["review", token], queryFn: () => review.get(token), retry: false })
  const decide = useMutation({
    mutationFn: (decision: "approved" | "changes_requested") => review.decide(token, decision, comment),
    onSuccess: (r) => qc.setQueryData(["review", token], r),
  })

  const shell = (children: React.ReactNode) => (
    <div className="min-h-svh bg-app">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex h-14 max-w-[820px] items-center gap-2.5 px-4 sm:px-6">
          <span className="inline-flex size-7 items-center justify-center rounded-md bg-brand text-on-brand">
            <Workflow className="size-4" strokeWidth={2.25} aria-hidden />
          </span>
          <span className="text-sm font-semibold">Transcript to BPMN</span>
          <Chip className="ml-auto">Review</Chip>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-[820px] px-4 py-8 sm:px-6">
        {children}
      </main>
    </div>
  )

  if (data.isPending) return shell(<p className="text-fg-muted">Loading your part of the process…</p>)
  if (data.error) {
    const gone = data.error instanceof ApiError && data.error.status === 410
    return shell(
      <>
        <PageHeader title={gone ? "This link has ended" : "Link not found"} />
        <p className="measure text-fg-muted">
          {data.error.message}. Ask the person who sent it for a new link.
          {gone ? "" : " Check that the whole link was copied."}
        </p>
      </>,
    )
  }
  const r = data.data
  const changed = r.version !== r.requested_version
  return shell(
    <>
      <PageHeader
        crumb={`For ${r.name}`}
        title={r.process}
        meta={`Your part: ${r.lanes.join(", ")} · map v${r.version} · link open until ${formatDay(r.expires_at)}`}
      />
      <p className="measure mb-6 text-[0.95rem] leading-relaxed text-fg-muted">
        This is how your part of the process was described in meetings. Check each step: is it right, is it complete, is
        the order correct? Then approve it or say what needs to change.
      </p>
      {changed && (
        <p className="mb-6 rounded-md border border-line bg-panel px-3 py-2 text-sm text-fg-muted">
          The map has been updated since this link was sent (v{r.requested_version} → v{r.version}); you're seeing the
          latest version.
        </p>
      )}

      <section aria-labelledby="your-steps" className="mb-8">
        <div className="mb-3 flex items-baseline gap-2">
          <h2 id="your-steps" className="text-base font-semibold">
            Your steps
          </h2>
          <span className="tabular text-sm text-fg-subtle">{r.steps.length}</span>
        </div>
        {r.steps.length ? (
          <ol className="space-y-3">
            {r.steps.map((s, i) => (
              <Step key={s.id} step={s} number={i + 1} />
            ))}
          </ol>
        ) : (
          <p className="text-fg-muted">No steps are in your part of the map any more.</p>
        )}
      </section>

      <Panel title="Your answer" id="your-answer">
        {r.decision && (
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm" role="status">
            <Chip tone={r.decision === "approved" ? "ok" : "warn"} icon={r.decision === "approved" ? Check : PenLine}>
              {r.decision === "approved" ? "Approved" : "Changes requested"}
            </Chip>
            <span className="text-fg-muted">
              You {r.decision === "approved" ? "approved" : "asked for changes to"} v{r.decided_version}
              {r.decided_at ? ` on ${formatDay(r.decided_at)}` : ""}.{r.comment ? ` “${r.comment}”` : ""} You can change
              your answer.
            </span>
          </div>
        )}
        <label htmlFor="review-comment" className="eyebrow mb-1.5 block">
          Comment (needed if something should change)
        </label>
        <Textarea
          id="review-comment"
          value={comment}
          maxLength={4000}
          rows={4}
          placeholder="e.g. We pay on Thursdays, not Fridays. Step 2 is done by Treasury, not Finance."
          onChange={(e) => setComment(e.target.value)}
        />
        {decide.error && (
          <p role="alert" className="mt-2 text-sm text-bad">
            {decide.error.message}
          </p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button disabled={decide.isPending} onClick={() => decide.mutate("approved")}>
            {decide.isPending && decide.variables === "approved" ? "Saving…" : "Approve my part"}
          </Button>
          <Button
            variant="outline"
            disabled={decide.isPending || !comment.trim()}
            onClick={() => decide.mutate("changes_requested")}
          >
            {decide.isPending && decide.variables === "changes_requested" ? "Saving…" : "Request changes"}
          </Button>
        </div>
      </Panel>
    </>,
  )
}
