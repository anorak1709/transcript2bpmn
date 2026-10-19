// Shared building blocks (design-system/transcript-to-bpmn/MASTER.md): page header, panels,
// semantic chips, quotes. Meaning is always icon + word; colour only reinforces it.
import { Check, CircleDashed, Clock, Loader2, X, type LucideIcon } from "lucide-react"

import { formatTimestamp, ROLE_LABEL, STATUS_LABEL } from "@/lib/format"
import type { Tone } from "@/lib/items"
import type { Job, Quote as QuoteT } from "@/lib/types"
import { cn } from "@/lib/utils"

const TONE: Record<Tone, string> = {
  ok: "bg-ok-tint text-ok",
  info: "bg-brand-tint text-brand",
  bad: "bg-bad-tint text-bad",
  warn: "bg-warn-tint text-warn",
  policy: "bg-policy-tint text-policy",
  gap: "bg-gap-tint text-gap",
  neutral: "bg-raised text-fg-muted",
}

/** A small tinted label: icon + word. */
export function Chip({
  tone = "neutral",
  icon: Icon,
  children,
  className,
  spin,
}: {
  tone?: Tone
  icon?: LucideIcon
  children: React.ReactNode
  className?: string
  spin?: boolean
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium whitespace-nowrap",
        TONE[tone],
        className,
      )}
    >
      {Icon && <Icon className={cn("size-3.5", spin && "animate-spin")} strokeWidth={2.25} aria-hidden />}
      {children}
    </span>
  )
}

/** Short id like "D2", the same one shown on the diagram. */
export function ItemId({ id, tone }: { id: string; tone: Tone }) {
  return (
    <span
      className={cn(
        "tabular inline-flex h-6 min-w-8 shrink-0 items-center justify-center rounded-md px-1.5 text-xs font-semibold",
        TONE[tone],
      )}
    >
      {id}
    </span>
  )
}

/** Processing status as a chip. */
export function StatusChip({ job, expired }: { job: Job | null; expired?: boolean }) {
  if (expired) return <Chip icon={CircleDashed}>Content expired</Chip>
  if (!job) return <Chip icon={CircleDashed}>Not processed</Chip>
  if (job.status === "done")
    return (
      <Chip tone="ok" icon={Check}>
        Done
      </Chip>
    )
  if (job.status === "failed")
    return (
      <Chip tone="bad" icon={X}>
        Failed
      </Chip>
    )
  if (job.status === "queued")
    return (
      <Chip tone="info" icon={Clock}>
        Queued
      </Chip>
    )
  return (
    <Chip tone="info" icon={Loader2} spin>
      {STATUS_LABEL[job.status]}…
    </Chip>
  )
}

/** Page head: optional breadcrumb, title, meta line, actions on the right. */
export function PageHeader({
  crumb,
  title,
  meta,
  actions,
  className,
}: {
  crumb?: React.ReactNode
  title: React.ReactNode
  meta?: React.ReactNode
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <header className={cn("mb-6", className)}>
      {crumb && (
        <div className="eyebrow mb-1.5 [&_a]:inline-flex [&_a]:min-h-6 [&_a]:items-center [&_a:hover]:text-fg">
          {crumb}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <h1 className="min-w-0 text-2xl break-words">{title}</h1>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {meta && <p className="tabular mt-1.5 text-sm text-fg-muted">{meta}</p>}
    </header>
  )
}

/** A panel: raised surface with a header row (title, aside) and a body. */
export function Panel({
  title,
  aside,
  children,
  className,
  bodyClassName,
  id,
}: {
  title?: React.ReactNode
  aside?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
  id?: string
}) {
  return (
    <section
      className={cn("rounded-lg border border-line bg-panel", className)}
      aria-labelledby={title ? id : undefined}
    >
      {title && (
        <div className="flex min-h-11 items-center justify-between gap-4 border-b border-line px-4 py-2">
          <h2 id={id} className="text-sm font-semibold">
            {title}
          </h2>
          {aside && <div className="text-xs text-fg-muted">{aside}</div>}
        </div>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  )
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="py-6 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-fg-muted">{children}</div>}
    </div>
  )
}

/** One line of evidence: what someone said, who, and when. */
export function Quote({ q, index }: { q: QuoteT; index?: number }) {
  const who = q.policy
    ? `Policy · ${q.meeting}`
    : [
        q.speaker ?? "Unknown speaker",
        q.role && ROLE_LABEL[q.role],
        [q.meeting, q.start_ts != null ? formatTimestamp(q.start_ts) : ""].filter(Boolean).join(" @ "),
      ]
        .filter(Boolean)
        .join(" · ")
  return (
    <figure className="flex gap-2">
      {index != null && (
        <span className="tabular w-4 shrink-0 pt-0.5 text-xs text-fg-subtle" aria-hidden>
          {index}
        </span>
      )}
      <div className="min-w-0 border-l-2 border-line-strong pl-3">
        <blockquote className="text-[0.95rem] leading-relaxed text-fg">
          {q.text ? `“${q.text}”` : <span className="text-fg-subtle">Source text no longer available.</span>}
        </blockquote>
        <figcaption className="mt-0.5 text-xs text-fg-muted">{who}</figcaption>
      </div>
    </figure>
  )
}
