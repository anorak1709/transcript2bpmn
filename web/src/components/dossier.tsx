// Shared page pieces in the industrial print style (design-system/transcript-to-bpmn/MASTER.md):
// uppercase macro type, mono telemetry, compartments drawn with ink rules, red only for "needs you".
import { Check, Circle, Contrast, X } from "lucide-react"

import { STATUS_LABEL } from "@/lib/format"
import type { Job } from "@/lib/types"
import { cn } from "@/lib/utils"

/** "[ TEXT ]": ASCII framing for labels. The brackets are decoration. */
export function Framed({ children }: { children: React.ReactNode }) {
  return (
    <>
      <span aria-hidden>[ </span>
      {children}
      <span aria-hidden> ]</span>
    </>
  )
}

/** Page head: a telemetry strip between two ink rules, then the macro title and its actions. */
export function PageHeader({
  eyebrow,
  title,
  revision,
  actions,
  code,
}: {
  eyebrow?: React.ReactNode
  title: React.ReactNode
  revision?: React.ReactNode
  actions?: React.ReactNode
  code?: React.ReactNode // telemetry on the right of the strip, e.g. "UNIT / P-01 · REV 4"
}) {
  return (
    <header className="mb-12">
      <div className="label xmarks mb-8 flex min-h-9 flex-wrap items-center justify-between gap-x-6 gap-y-1 border-y-2 border-fg py-1.5 [&_a]:inline-flex [&_a]:min-h-7 [&_a]:items-center">
        <span>{eyebrow ?? <span aria-hidden>///</span>}</span>
        {code && <span className="tabular text-fg-subtle">{code}</span>}
      </div>
      <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-6">
        <h1 className="macro min-w-0 text-[clamp(2.75rem,8vw,7rem)] break-words">{title}</h1>
        {actions && <div className="flex flex-wrap items-center gap-2 pb-1">{actions}</div>}
      </div>
      {revision && <p className="label tabular mt-5">{revision}</p>}
    </header>
  )
}

/** A compartment: ink rule across the top, framed mono title, optional telemetry on the right. */
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
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t-2 border-fg pt-2.5">
        <h2 id={id} className="label font-semibold whitespace-nowrap text-fg">
          <Framed>{title}</Framed>
        </h2>
        {aside && <div className="label text-fg-subtle sm:text-right">{aside}</div>}
      </div>
      {children}
    </section>
  )
}

/** Job status as a glyph + words (never colour alone). */
export function StatusMark({ job, expired }: { job: Job | null; expired?: boolean }) {
  const [Icon, text, extra] = expired
    ? [Circle, "Content expired", "text-fg-subtle"]
    : !job
      ? [Circle, "Not processed", "text-fg-subtle"]
      : job.status === "done"
        ? [Check, "Done", "text-fg"]
        : job.status === "failed"
          ? [X, "Failed", "text-signal"]
          : [Contrast, `${STATUS_LABEL[job.status]}…`, "text-fg"]
  return (
    <span className={cn("label inline-flex items-center gap-1.5 whitespace-nowrap", extra)}>
      <Icon className="size-4 shrink-0" strokeWidth={2.5} aria-hidden />
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
    <figure className="grid grid-cols-[2rem_1fr] gap-x-2">
      <span className="label tabular pt-1 text-fg-subtle" aria-hidden>
        {String(index).padStart(2, "0")}
      </span>
      <div className="border-l-2 border-fg pl-3">
        <blockquote className="leading-relaxed">“{text}”</blockquote>
        <figcaption className="label mt-1.5">
          {speaker}
          {when ? ` · ${when}` : ""}
        </figcaption>
      </div>
    </figure>
  )
}
