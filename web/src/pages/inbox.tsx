import { useQuery } from "@tanstack/react-query"
import { ArrowRight, Check, PenLine, X } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router"

import { Page } from "@/components/app-shell"
import { Chip, Empty, ItemId, PageHeader } from "@/components/kit"
import { ITEM, type Tone } from "@/lib/items"
import { NewProcessDialog } from "@/components/new-process"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { formatDate } from "@/lib/format"
import type { InboxItem } from "@/lib/types"
import { cn } from "@/lib/utils"

type Filter = "all" | InboxItem["kind"]

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "disagreement", label: "Disagreements" },
  { key: "policy", label: "Policy" },
  { key: "gap", label: "Gaps" },
  { key: "signoff", label: "Sign-offs" },
  { key: "failed", label: "Failed" },
]

function Marker({ item }: { item: InboxItem }) {
  if (item.kind === "disagreement" || item.kind === "policy" || item.kind === "gap") {
    const k = item.kind === "disagreement" ? ITEM.disagreement : item.kind === "policy" ? ITEM.policy : ITEM.gap
    return <ItemId id={item.ref ?? "?"} tone={k.tone} />
  }
  if (item.kind === "failed")
    return (
      <Chip tone="bad" icon={X}>
        Failed
      </Chip>
    )
  const approved = item.title.endsWith("approved their part")
  return (
    <Chip tone={approved ? "ok" : ("warn" as Tone)} icon={approved ? Check : PenLine}>
      {approved ? "Approved" : "Changes"}
    </Chip>
  )
}

/** Home: everything waiting on someone, across all processes. */
export function InboxPage() {
  const [filter, setFilter] = useState<Filter>("all")
  const [creating, setCreating] = useState(false)
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: api.inbox, refetchInterval: 15_000 })
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects })

  const all = inbox.data ?? []
  const shown = filter === "all" ? all : all.filter((i) => i.kind === filter)
  const byProject = new Map<string, InboxItem[]>()
  for (const i of shown) byProject.set(i.project_id, [...(byProject.get(i.project_id) ?? []), i])
  const nProjects = new Set(all.map((i) => i.project_id)).size
  const count = (k: Filter) => (k === "all" ? all.length : all.filter((i) => i.kind === k).length)

  return (
    <Page>
      <PageHeader
        title="Inbox"
        meta={
          inbox.data
            ? all.length
              ? `${all.length} open item${all.length === 1 ? "" : "s"} across ${nProjects} process${nProjects === 1 ? "" : "es"}`
              : "Nothing waiting on you"
            : undefined
        }
        actions={<Button onClick={() => setCreating(true)}>New process</Button>}
      />
      <NewProcessDialog open={creating} onOpenChange={setCreating} />

      {all.length > 0 && (
        <div className="mb-5 flex flex-wrap gap-1.5" role="group" aria-label="Filter by kind">
          {FILTERS.filter((f) => f.key === "all" || count(f.key)).map((f) => (
            <button
              key={f.key}
              type="button"
              aria-pressed={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                "transition-quiet inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-sm",
                filter === f.key
                  ? "border-brand/60 bg-brand-tint text-fg"
                  : "border-line bg-panel text-fg-muted hover:border-line-strong hover:text-fg",
              )}
            >
              {f.label}
              <span className="tabular text-xs text-fg-subtle">{count(f.key)}</span>
            </button>
          ))}
        </div>
      )}

      {inbox.isPending || projects.isPending ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-28 rounded-lg bg-panel" />
          ))}
        </div>
      ) : projects.data?.length === 0 ? (
        <div className="rounded-lg border border-line bg-panel p-8">
          <Empty title="No processes yet">
            Create one, then add a meeting transcript or recording. The map is drafted from what was said, and every
            step keeps the quotes behind it.
            <div className="mt-4">
              <Button onClick={() => setCreating(true)}>Create your first process</Button>
            </div>
          </Empty>
        </div>
      ) : shown.length === 0 ? (
        <div className="rounded-lg border border-line bg-panel p-8">
          <Empty title="You're all caught up">
            No open disagreements, policy differences or gaps, and no sign-offs waiting.
          </Empty>
        </div>
      ) : (
        <div className="space-y-4">
          {[...byProject].map(([pid, items]) => (
            <section key={pid} className="rounded-lg border border-line bg-panel" aria-labelledby={`inbox-${pid}`}>
              <div className="flex min-h-11 items-center justify-between gap-3 border-b border-line px-4 py-2">
                <h2 id={`inbox-${pid}`} className="truncate text-sm font-semibold">
                  {items[0].project_name}
                </h2>
                <Link
                  to={`/projects/${pid}`}
                  className="inline-flex min-h-6 items-center gap-1 text-xs text-fg-muted hover:text-fg"
                >
                  Open process <ArrowRight className="size-3.5" aria-hidden />
                </Link>
              </div>
              <ul className="divide-y divide-line">
                {items.map((i, k) => (
                  <li key={k}>
                    <Link
                      to={`/projects/${pid}?tab=${i.tab}${i.ref ? `#${i.ref}` : ""}`}
                      className="transition-quiet group flex items-start gap-3 px-4 py-3 hover:bg-raised"
                    >
                      <Marker item={i} />
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-2 text-sm text-fg">{i.title}</p>
                        {i.detail && <p className="mt-0.5 line-clamp-1 text-xs text-fg-muted">{i.detail}</p>}
                      </div>
                      {i.at && (
                        <span className="tabular hidden shrink-0 text-xs text-fg-subtle sm:block">
                          {formatDate(i.at)}
                        </span>
                      )}
                      <ArrowRight className="mt-0.5 size-4 shrink-0 text-fg-subtle group-hover:text-fg" aria-hidden />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Page>
  )
}
