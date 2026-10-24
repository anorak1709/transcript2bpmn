import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { useParams } from "react-router"

import { PageHeader, Section, SourceQuote } from "@/components/dossier"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, review } from "@/lib/api"
import { formatDay, formatTimestamp } from "@/lib/format"
import type { ReviewStep } from "@/lib/types"

function Step({ step, number }: { step: ReviewStep; number: number }) {
  const from = step.comes_from.map((n) => `${n.name}${n.lane && n.lane !== step.lane ? ` (${n.lane})` : ""}`)
  const to = step.goes_to.map(
    (n) =>
      `${n.condition ? `if ${n.condition}: ` : ""}${n.name}${n.lane && n.lane !== step.lane ? ` (${n.lane})` : ""}`,
  )
  return (
    <li className="grid grid-cols-[2.5rem_1fr] gap-x-3 border-b-2 border-fg py-5">
      <span className="macro tabular text-[1.75rem] text-fg-subtle" aria-hidden>
        {String(number).padStart(2, "0")}
      </span>
      <div className="min-w-0 space-y-1.5">
        <p className="label">
          {step.kind === "decision" ? "Decision" : "Step"} · {step.lane}
        </p>
        <h3 className="macro text-[1.4rem]">{step.name}</h3>
        <dl className="grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-0.5 text-sm">
          <dt className="text-fg-muted">Comes after</dt>
          <dd>{from.length ? from.join("; ") : "The start of the process"}</dd>
          <dt className="text-fg-muted">Then</dt>
          <dd>{to.length ? to.join("; ") : "The process ends"}</dd>
        </dl>
        {step.quotes.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-fg-muted select-none hover:text-fg">Where this came from</summary>
            <ol className="mt-2 space-y-3">
              {step.quotes.map((q, i) => (
                <li key={i}>
                  <SourceQuote
                    index={i + 1}
                    speaker={q.policy ? "Policy" : (q.speaker ?? "Unknown speaker")}
                    when={[q.meeting, q.start_ts != null ? formatTimestamp(q.start_ts) : ""]
                      .filter(Boolean)
                      .join(" · ")}
                    text={q.text ?? "Source text no longer available."}
                  />
                </li>
              ))}
            </ol>
          </details>
        )}
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
    <div className="min-h-svh bg-bg">
      <header className="border-b-2 border-fg">
        <div className="mx-auto flex h-14 max-w-[820px] items-center px-4 sm:px-6">
          <span className="macro text-[1.15rem] leading-none">
            Transcript
            <span className="text-hazard" aria-hidden>
              →
            </span>
            <span className="sr-only"> to </span>BPMN
          </span>
          <span className="label ml-auto">[ Sign-off ]</span>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-[820px] px-4 pt-10 pb-20 sm:px-6">
        {children}
      </main>
    </div>
  )

  if (data.isPending) return shell(<p className="text-fg-muted">Loading your part of the process…</p>)
  if (data.error) {
    const gone = data.error instanceof ApiError && data.error.status === 410
    return shell(
      <>
        <PageHeader eyebrow="Review" title={gone ? "This link has ended" : "Link not found"} />
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
        eyebrow={`For ${r.name}`}
        title={r.process}
        revision={`Your part: ${r.lanes.join(", ")} · map v${r.version} · link open until ${formatDay(r.expires_at)}`}
      />
      <p className="measure mb-10 text-[1.1rem] leading-relaxed">
        This is how your part of the process was described in meetings. Please check each step: is it right, is it
        complete, is the order correct? Then approve it or say what needs to change.
        {changed && (
          <span className="mt-2 block text-[0.95rem] text-fg-muted">
            The map has been updated since this link was sent (v{r.requested_version} → v{r.version}); you're seeing the
            latest version.
          </span>
        )}
      </p>

      <Section title="Your steps" aside={`${r.steps.length} to check`}>
        {r.steps.length ? (
          <ol>
            {r.steps.map((s, i) => (
              <Step key={s.id} step={s} number={i + 1} />
            ))}
          </ol>
        ) : (
          <p className="text-fg-muted">No steps are in your part of the map any more.</p>
        )}
      </Section>

      <Section title="Your answer" className="mt-12">
        {r.decision && (
          <p className="mb-4 border-l-2 border-fg bg-surface py-2 pl-3 text-sm" role="status">
            You {r.decision === "approved" ? "approved" : "asked for changes to"} v{r.decided_version}
            {r.decided_at ? ` on ${formatDay(r.decided_at)}` : ""}.{r.comment ? ` “${r.comment}”` : ""} You can change
            your answer below.
          </p>
        )}
        <label htmlFor="review-comment" className="label mb-1.5 block">
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
          <p role="alert" className="mt-2 text-sm text-signal">
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
      </Section>
    </>,
  )
}
