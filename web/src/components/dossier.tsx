// Shared page pieces in the Swiss workbench style (design-system/transcript-to-bpmn/MASTER.md):
// big clear type, a strict grid, space instead of ornament, signal red only for "needs you".
import { Check, Circle, Contrast, X } from "lucide-react"

import { STATUS_LABEL } from "@/lib/format"
import type { Job } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Page head: small label, large title, one line of facts, actions on the right. */
export function PageHeader({
  eyebrow,
  title,
  revision,
  actions,
}: {
  eyebrow?: React.ReactNode
  title: React.ReactNode
  revision?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <header className="mb-10">
      {eyebrow && <div className="label mb-3 [&_a]:inline-flex [&_a]:min-h-7 [&_a]:items-center">{eyebrow}</div>}
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <h1 className="min-w-0 text-[2.25rem] leading-[1.05] break-words sm:text-[3rem]">{title}</h1>
        {actions && <div className="flex flex-wrap items-center gap-2 pb-1">{actions}</div>}
      </div>
      {revision && <p className="tabular mt-3 text-fg-muted">{revision}</p>}
    </header>
  )
}

/** A section: uppercase label over its content, grouped by space. */
export function Section({
  title,
  aside,
  children,
  className,
  id,
}: {
  title: React.ReactNode
  aside?: React.ReactNode
  children: React.ReactNode
  className?: string
  id?: string
}) {
  return (
    <section className={className} aria-labelledby={id}>
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h2 id={id} className="label">
          {title}
        </h2>
        {aside && <div className="text-sm text-fg-muted">{aside}</div>}
      </div>
      {children}
    </section>
  )
}

/** Job status as a glyph + words (never colour alone). */
export function StatusMark({ job, expired }: { job: Job | null; expired?: boolean }) {
  const [Icon, text, extra] = expired
    ? [Circle, "Content expired", "text-fg-muted"]
    : !job
      ? [Circle, "Not processed", "text-fg-muted"]
      : job.status === "done"
        ? [Check, "Done", "text-fg"]
        : job.status === "failed"
          ? [X, "Failed", "text-signal"]
          : [Contrast, `${STATUS_LABEL[job.status]}…`, "text-fg"]
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm whitespace-nowrap", extra)}>
      <Icon className="size-4 shrink-0" strokeWidth={2.25} aria-hidden />
      {text}
    </span>
  )
}

/** A source quote: the words, then who said it and when. */
export function SourceQuote({
  index,
  speaker,
  when,
  text,
}: {
  index: number
  speaker: string
  when?: string
  text: string
}) {
  return (
    <figure className="grid grid-cols-[1.5rem_1fr] gap-x-1">
      <span className="tabular pt-0.5 text-sm text-fg-subtle" aria-hidden>
        {index}
      </span>
      <div className="border-l-2 border-line-strong pl-3">
        <blockquote className="leading-relaxed">“{text}”</blockquote>
        <figcaption className="mt-1 text-sm text-fg-muted">
          {speaker}
          {when ? ` · ${when}` : ""}
        </figcaption>
      </div>
    </figure>
  )
}
