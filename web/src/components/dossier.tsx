// Dossier building blocks (design-system/transcript-to-bpmn/MASTER.md).
import { Check, ChevronRight, Circle, Contrast, X } from "lucide-react"

import { STATUS_LABEL } from "@/lib/format"
import type { Job } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Page head: muted eyebrow, title, one rule, revision line. */
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
    <header className="mb-12">
      {eyebrow && <div className="label mb-1 [&_a]:inline-flex [&_a]:min-h-7 [&_a]:items-center">{eyebrow}</div>}
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4 border-b border-rule pb-4">
        <h1 className="min-w-0 text-[1.6rem] leading-[1.15] break-words sm:text-[1.9rem]">{title}</h1>
        {actions && <div className="flex flex-wrap items-center gap-2 pb-1">{actions}</div>}
      </div>
      {revision && <p className="mt-3 text-sm text-graphite tabular">{revision}</p>}
    </header>
  )
}

/** A section: muted label, then its content. Grouped by space, not by rules. */
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
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <h2 id={id} className="label font-sans">
          {title}
        </h2>
        {aside && <div className="text-xs text-graphite">{aside}</div>}
      </div>
      {children}
    </section>
  )
}

/** A section folded into one row (title, count, chevron) until opened (MASTER: progressive page). */
export function Fold({
  title,
  count,
  aside,
  children,
  defaultOpen = false,
  id,
  attention,
}: {
  title: React.ReactNode
  count?: number
  aside?: React.ReactNode
  children: React.ReactNode
  defaultOpen?: boolean
  id?: string
  attention?: boolean // the count needs action (oxblood), e.g. open policy differences
}) {
  return (
    <details open={defaultOpen} className="group/fold border-b border-hairline" id={id}>
      <summary className="transition-quiet flex min-h-12 cursor-pointer items-center gap-3 py-3 select-none hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="size-4 shrink-0 text-graphite transition-transform group-open/fold:rotate-90"
          aria-hidden
        />
        <h2 className="text-[1.05rem] font-bold">{title}</h2>
        {count != null && (
          <span className={cn("tabular text-sm", attention && count > 0 ? "text-oxblood" : "text-graphite")}>
            {count}
          </span>
        )}
        {aside && <span className="ml-auto text-xs text-graphite">{aside}</span>}
      </summary>
      <div className="pt-1 pb-8">{children}</div>
    </details>
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

/** A source quote set like a footnote: the words, then who and when. */
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
      <span className="pt-0.5 text-xs text-graphite tabular" aria-hidden>
        {index}
      </span>
      <div>
        <blockquote className="text-[1.05rem] leading-snug">“{text}”</blockquote>
        <figcaption className="mt-1 text-xs text-graphite">
          {speaker}
          {when ? ` · ${when}` : ""}
        </figcaption>
      </div>
    </figure>
  )
}
