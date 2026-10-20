// Dossier building blocks (design-system/transcript-to-bpmn/MASTER.md).
import { Check, Circle, Contrast, X } from "lucide-react"

import { STATUS_LABEL } from "@/lib/format"
import type { Job } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Page head: small-caps eyebrow, serif title, hairline rule, revision line. */
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
      {eyebrow && <div className="label mb-1 [&_a]:inline-flex [&_a]:min-h-7 [&_a]:items-center">{eyebrow}</div>}
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4 border-b border-rule pb-4">
        <h1 className="min-w-0 text-[2rem] leading-[1.1] break-words sm:text-[2.5rem]">{title}</h1>
        {actions && <div className="flex flex-wrap items-center gap-2 pb-1">{actions}</div>}
      </div>
      {revision && <p className="mt-3 text-sm text-graphite tabular">{revision}</p>}
    </header>
  )
}

/** Small-caps section label with a hairline under it. */
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
      <div className="mb-3 flex items-baseline justify-between gap-4 border-b border-hairline pb-1.5">
        <h2 id={id} className="label font-sans">
          {title}
        </h2>
        {aside && <div className="text-xs text-graphite">{aside}</div>}
      </div>
      {children}
    </section>
  )
}

/** Job status as a monochrome glyph + words (never colour alone). */
export function StatusMark({ job, expired }: { job: Job | null; expired?: boolean }) {
  const [Icon, text, extra] = expired
    ? [Circle, "Content expired", "text-graphite"]
    : !job
      ? [Circle, "Not processed", "text-graphite"]
      : job.status === "done"
        ? [Check, "Done", "text-ink"]
        : job.status === "failed"
          ? [X, "Failed", "text-ink"]
          : [Contrast, `${STATUS_LABEL[job.status]}…`, "text-ink"]
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm whitespace-nowrap", extra)}>
      <Icon className="size-3.5 shrink-0" strokeWidth={2.25} aria-hidden />
      {text}
    </span>
  )
}

/** A source quote set like a footnote: italic serif, small-caps attribution. */
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
    <figure className="grid grid-cols-[1.25rem_1fr] gap-x-1 text-[0.95rem]">
      <span className="serif pt-0.5 text-xs text-graphite tabular" aria-hidden>
        {index}
      </span>
      <div>
        <blockquote className="serif text-[1.05rem] leading-snug italic">“{text}”</blockquote>
        <figcaption className="smallcaps mt-1 text-xs text-graphite">
          {speaker}
          {when ? ` · ${when}` : ""}
        </figcaption>
      </div>
    </figure>
  )
}
