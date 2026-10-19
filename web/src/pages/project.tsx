import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Download, FileText, MoreHorizontal, ScrollText } from "lucide-react"
import { useEffect, useState } from "react"
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
import { ConflictPoint, PolicyDifference } from "@/components/conflict-card"
import { Empty, PageHeader, Panel, StatusChip } from "@/components/kit"
import { ITEM } from "@/lib/items"
import { AddFiles, Gaps, RequestSignoff, Signoffs, Speakers } from "@/components/process-file"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api, downloadAgenda, downloadExport } from "@/lib/api"
import { ACCEPTED_UPLOADS, countOf, formatDay, formatDuration } from "@/lib/format"
import { isActive, type Project, type Resolution, type Transcript } from "@/lib/types"
import { cn } from "@/lib/utils"

const TONE_TEXT: Record<string, string> = { warn: "text-warn", policy: "text-policy", gap: "text-gap" }
const TABS = ["review", "sources", "signoff", "settings"] as const
type Tab = (typeof TABS)[number]
const TAB_LABEL: Record<Tab, string> = {
  review: "Review",
  sources: "Sources",
  signoff: "Sign-off",
  settings: "Settings",
}

function FileRow({ t, projectId }: { t: Transcript; projectId: string }) {
  const qc = useQueryClient()
  const process = useMutation({
    mutationFn: () => api.process(t.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["project", projectId] }),
    onError: (e) => toast.error(e.message),
  })
  const job = t.latest_job
  const canProcess = !t.content_expired && !isActive(job)
  const Icon = t.purpose === "policy" ? ScrollText : FileText
  return (
    <tr className="align-middle">
      <td className="max-w-0 py-2.5 pr-3">
        <div className="flex items-center gap-2.5">
          <Icon className="size-4 shrink-0 text-fg-subtle" aria-hidden />
          <span className="truncate font-medium" title={t.filename}>
            {t.filename}
          </span>
        </div>
        {job?.status === "failed" && job.error && (
          <p className="mt-1 ml-6.5 line-clamp-2 text-xs text-bad">{job.error}</p>
        )}
      </td>
      <td className="tabular hidden py-2.5 pr-3 whitespace-nowrap text-fg-muted md:table-cell">
        {formatDay(t.created_at)}
      </td>
      <td className="tabular hidden py-2.5 pr-3 whitespace-nowrap text-fg-muted sm:table-cell">
        {t.segment_count != null ? `${t.segment_count} lines` : formatDuration(t.duration_seconds)}
      </td>
      <td className="py-2.5 pr-1" aria-live="polite">
        <StatusChip job={job} expired={t.content_expired} />
      </td>
      <td className="w-10 py-1 text-right">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${t.filename}`}>
              <MoreHorizontal aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {job?.map_id && (
              <DropdownMenuItem asChild>
                <Link to={`/maps/${job.map_id}`}>
                  {t.purpose === "policy" ? "Open the map read from this policy" : "Open this meeting's own map"}
                </Link>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem disabled={!canProcess} onSelect={() => process.mutate()}>
              {job ? "Process again" : "Process"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </td>
    </tr>
  )
}

function FileTable({ files, projectId, caption }: { files: Transcript[]; projectId: string; caption: string }) {
  return (
    <table className="mb-4 w-full table-fixed text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-line text-left text-xs text-fg-muted">
          <th className="pb-2 font-medium">File</th>
          <th className="hidden w-32 pb-2 font-medium md:table-cell">Added</th>
          <th className="hidden w-24 pb-2 font-medium sm:table-cell">Length</th>
          <th className="w-40 pb-2 font-medium">Status</th>
          <th className="w-10 pb-2">
            <span className="sr-only">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {files.map((t) => (
          <FileRow key={t.id} t={t} projectId={projectId} />
        ))}
      </tbody>
    </table>
  )
}

function DeleteProcess({ project }: { project: Project }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [typed, setTyped] = useState("")
  const del = useMutation({
    mutationFn: () => api.deleteProject(project.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] })
      qc.invalidateQueries({ queryKey: ["inbox"] })
      toast.success(`Deleted "${project.name}"`)
      navigate("/")
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <AlertDialog onOpenChange={() => setTyped("")}>
      <AlertDialogTrigger asChild>
        <Button variant="destructive">Delete this process…</Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete “{project.name}”?</AlertDialogTitle>
          <AlertDialogDescription>
            Every recording, transcript, policy document, map, version and sign-off link in this process is permanently
            deleted. The audit log keeps a record that it happened. This can't be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-1.5">
          <label htmlFor="confirm-name" className="eyebrow block">
            Type the process name to confirm
          </label>
          <Input id="confirm-name" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep it</AlertDialogCancel>
          <AlertDialogAction
            className="bg-bad text-app hover:bg-bad/90"
            disabled={typed !== project.name || del.isPending}
            onClick={(e) => {
              e.preventDefault()
              del.mutate()
            }}
          >
            {del.isPending ? "Deleting…" : "Delete permanently"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function ExportMenu({ mapId }: { mapId: string }) {
  const run = (format: "bpmn" | "svg" | "png" | "md") =>
    downloadExport(mapId, format).catch((e: Error) => toast.error(e.message))
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline">
          <Download aria-hidden /> Export
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => run("bpmn")}>BPMN 2.0 file</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("md")}>Written procedure (SOP)</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("png")}>Diagram image (PNG)</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("svg")}>Diagram vector (SVG)</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function SectionHead({ title, count, hint }: { title: string; count?: number; hint?: string }) {
  return (
    <div className="mb-3 flex items-baseline gap-2">
      <h2 className="text-base font-semibold">{title}</h2>
      {count != null && <span className="tabular text-sm text-fg-subtle">{count}</span>}
      {hint && <span className="ml-auto text-xs text-fg-muted">{hint}</span>}
    </div>
  )
}

export function ProjectPage() {
  const { projectId = "" } = useParams()
  const [params, setParams] = useSearchParams()
  const { hash } = useLocation()
  const tab: Tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "review"
  const qc = useQueryClient()
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.project(projectId),
    // Poll while anything is processing; stop when everything has settled.
    refetchInterval: (q) => (q.state.data?.transcripts.some((t) => isActive(t.latest_job)) ? 2000 : false),
  })
  // Refetch whenever another file finishes processing, or the map changes.
  const merged = project.data?.transcripts.filter((t) => t.latest_job?.status === "done").length ?? 0
  const refresh = `${merged}:${project.data?.map_version ?? 0}`
  const conflicts = useQuery({
    queryKey: ["conflicts", projectId, refresh],
    queryFn: () => api.conflicts(projectId, { status: "open" }),
    enabled: !!project.data?.merged_map_id,
  })
  const gaps = useQuery({
    queryKey: ["gaps", projectId, refresh],
    queryFn: () => api.gaps(projectId),
    enabled: !!project.data?.merged_map_id,
  })
  const signoffs = useQuery({ queryKey: ["signoffs", projectId], queryFn: () => api.signoffs(projectId) })

  // Deep links from the inbox (#D2): scroll once the item has rendered.
  const ready = !!conflicts.data && !!gaps.data
  useEffect(() => {
    if (ready && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" })
  }, [ready, hash, tab])

  const resolve = async (id: string, how: Resolution) => {
    try {
      await api.resolveConflict(id, how)
      toast.success("option" in how || "variant" in how ? "Applied to the map" : "Marked as settled")
      const keys = [["conflicts", projectId], ["project", projectId], ["gaps", projectId], ["projects"], ["inbox"]]
      await Promise.all(keys.map((queryKey) => qc.invalidateQueries({ queryKey })))
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (project.isPending) {
    return (
      <Page>
        <Skeleton className="mb-6 h-10 w-1/2 rounded-md bg-panel" />
        <Skeleton className="h-64 rounded-lg bg-panel" />
      </Page>
    )
  }
  if (project.error) {
    return (
      <Page>
        <PageHeader title="Process not found" />
        <p className="text-fg-muted">
          It may have been deleted, or it belongs to another workspace.{" "}
          <Link to="/" className="text-brand underline-offset-4 hover:underline">
            Back to the inbox
          </Link>
        </p>
      </Page>
    )
  }
  const p = project.data
  const meetings = p.transcripts.filter((t) => t.purpose === "meeting")
  const policies = p.transcripts.filter((t) => t.purpose === "policy")
  const processing = p.transcripts.filter((t) => isActive(t.latest_job)).length
  const points = (conflicts.data ?? []).filter((c) => c.origin === "meeting")
  const differences = (conflicts.data ?? []).filter((c) => c.origin === "policy")
  const gapList = gaps.data ?? []
  const pendingSignoffs = (signoffs.data ?? []).filter((s) => s.status === "pending").length
  const counts: Record<Tab, number | null> = {
    review: p.merged_map_id ? points.length + differences.length + gapList.length : null,
    sources: p.transcripts.length,
    signoff: signoffs.data?.length ?? null,
    settings: null,
  }
  const go = (t: Tab) => setParams(t === "review" ? {} : { tab: t }, { replace: true })

  return (
    <Page>
      <PageHeader
        title={p.name}
        meta={
          <>
            {countOf(meetings.length, "meeting")}
            {policies.length ? ` · ${countOf(policies.length, "policy document").toLowerCase()}` : ""}
            {p.map_version ? ` · v${p.map_version}` : ""}
            {p.revised_at ? ` · revised ${formatDay(p.revised_at)}` : ""}
            {processing ? ` · processing ${countOf(processing, "file").toLowerCase()}…` : ""}
          </>
        }
        actions={
          p.merged_map_id && (
            <>
              <ExportMenu mapId={p.merged_map_id} />
              <Button
                variant="outline"
                onClick={() => downloadAgenda(p.id).catch((e: Error) => toast.error(e.message))}
              >
                Next meeting's agenda
              </Button>
              <Button asChild>
                <Link to={`/maps/${p.merged_map_id}`}>Open the map</Link>
              </Button>
            </>
          )
        }
      />

      <div role="tablist" aria-label="Process" className="mb-6 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            id={`tab-${t}`}
            type="button"
            aria-selected={tab === t}
            aria-controls={`panel-${t}`}
            onClick={() => go(t)}
            className={cn(
              "transition-quiet -mb-px inline-flex h-10 items-center gap-2 border-b-2 px-3 text-sm whitespace-nowrap",
              tab === t ? "border-brand font-medium text-fg" : "border-transparent text-fg-muted hover:text-fg",
            )}
          >
            {TAB_LABEL[t]}
            {counts[t] != null && counts[t]! > 0 && (
              <span
                className={cn(
                  "tabular inline-flex h-5 min-w-5 items-center justify-center rounded-md px-1.5 text-xs font-semibold",
                  t === "review" ? "bg-warn-tint text-warn" : "bg-raised text-fg-muted",
                )}
              >
                {counts[t]}
              </span>
            )}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "review" &&
          (!p.merged_map_id ? (
            <Panel>
              <Empty title="Nothing to review yet">
                Add a meeting under Sources. Disagreements appear once a second meeting is merged.
                <div className="mt-4">
                  <Button onClick={() => go("sources")}>Add a meeting</Button>
                </div>
              </Empty>
            </Panel>
          ) : conflicts.isPending ? (
            <Skeleton className="h-48 rounded-lg bg-panel" />
          ) : (
            <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_260px]">
              <div className="min-w-0 space-y-8">
                <section aria-labelledby="h-disagreements">
                  <span id="h-disagreements" className="sr-only">
                    Disagreements
                  </span>
                  <SectionHead
                    title="Disagreements"
                    count={points.length}
                    hint="Where the meetings contradict each other"
                  />
                  {points.length ? (
                    <div className="space-y-3">
                      {points.map((c, i) => (
                        <ConflictPoint
                          key={c.id}
                          itemId={`D${i + 1}`}
                          conflict={c}
                          onResolve={(how) => resolve(c.id, how)}
                        />
                      ))}
                    </div>
                  ) : (
                    <Panel>
                      <Empty title="The meetings agree">Nothing to settle.</Empty>
                    </Panel>
                  )}
                </section>

                {policies.length > 0 && (
                  <section>
                    <SectionHead
                      title="Against the policy"
                      count={differences.length}
                      hint="What people said vs. what's written"
                    />
                    {differences.length ? (
                      <div className="space-y-3">
                        {differences.map((c, i) => (
                          <PolicyDifference
                            key={c.id}
                            itemId={`P${i + 1}`}
                            conflict={c}
                            onResolve={(how) => resolve(c.id, how)}
                          />
                        ))}
                      </div>
                    ) : (
                      <Panel>
                        <Empty title={processing ? "Comparing…" : "Matches the policy"} />
                      </Panel>
                    )}
                  </section>
                )}

                <section>
                  <SectionHead title="Gaps" count={gapList.length} hint="What nobody said" />
                  {gapList.length ? (
                    <Gaps gaps={gapList} projectId={p.id} />
                  ) : (
                    <Panel>
                      <Empty title="No gaps found">Every decision has its outcomes and every step has an owner.</Empty>
                    </Panel>
                  )}
                </section>
              </div>

              <aside className="hidden xl:block">
                <div className="sticky top-6 space-y-3">
                  <Panel title="At a glance" bodyClassName="space-y-1 p-2">
                    {[
                      { k: ITEM.disagreement, n: points.length, href: "#D1", label: "Disagreements" },
                      ...(policies.length
                        ? [{ k: ITEM.policy, n: differences.length, href: "#P1", label: "Policy differences" }]
                        : []),
                      { k: ITEM.gap, n: gapList.length, href: "#G1", label: "Gaps" },
                    ].map(({ k, n, href, label }) => (
                      <a
                        key={label}
                        href={n ? href : undefined}
                        className={cn(
                          "flex h-9 items-center gap-2.5 rounded-md px-2 text-sm",
                          n ? "hover:bg-raised" : "pointer-events-none text-fg-subtle",
                        )}
                      >
                        <k.icon className={cn("size-4", n && TONE_TEXT[k.tone])} aria-hidden />
                        {label}
                        <span className="tabular ml-auto text-fg-muted">{n}</span>
                      </a>
                    ))}
                  </Panel>
                  {pendingSignoffs > 0 && (
                    <p className="px-1 text-xs text-fg-muted">
                      {countOf(pendingSignoffs, "sign-off")} awaiting review.{" "}
                      <button type="button" onClick={() => go("signoff")} className="text-brand hover:underline">
                        View
                      </button>
                    </p>
                  )}
                </div>
              </aside>
            </div>
          ))}

        {tab === "sources" && (
          <div className="space-y-6">
            <Panel title="Meetings" aside={processing ? "Processing…" : "Merged into one map"} id="h-meetings">
              {meetings.length > 0 && (
                <FileTable files={meetings} projectId={p.id} caption="Meetings in this process" />
              )}
              <AddFiles
                project={p}
                purpose="meeting"
                accept={ACCEPTED_UPLOADS}
                prompt="Add a recording or transcript"
                hint="Drop files here · .vtt .srt .txt .docx or .mp3 .m4a .wav .webm .mp4 · processing starts on its own"
              />
            </Panel>
            <Panel title="Policy documents" aside="Compared with the map, never merged into it" id="h-policies">
              {policies.length > 0 && <FileTable files={policies} projectId={p.id} caption="Policy documents" />}
              <AddFiles
                project={p}
                purpose="policy"
                accept=".docx,.txt"
                prompt="Add the written SOP or policy"
                hint="Drop files here · .docx or .txt · differences appear under Review"
              />
            </Panel>
            <Panel title="Speakers" aside="Tag each person's role once; it shows next to their quotes" id="h-speakers">
              <Speakers projectId={p.id} refresh={merged} />
            </Panel>
          </div>
        )}

        {tab === "signoff" && (
          <Panel title="Sign-off" aside={<RequestSignoff project={p} />} id="h-signoff">
            <Signoffs project={p} />
          </Panel>
        )}

        {tab === "settings" && (
          <div className="space-y-6">
            <Panel title="Details" id="h-details">
              <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-[200px_1fr]">
                <dt className="text-fg-muted">Name</dt>
                <dd>{p.name}</dd>
                <dt className="text-fg-muted">Meeting content kept</dt>
                <dd>
                  {p.retention_days
                    ? `${p.retention_days} days, then recordings and transcript text are deleted (maps are kept)`
                    : "Until the process is deleted"}
                </dd>
                <dt className="text-fg-muted">Map</dt>
                <dd className="tabular">
                  {p.map_version ? `v${p.map_version}, revised ${formatDay(p.revised_at)}` : "Not made yet"}
                </dd>
              </dl>
            </Panel>
            <Panel title="Delete" id="h-danger" className="border-bad/30">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <p className="text-sm text-fg-muted">
                  Deletes every recording, transcript, policy document and map in this process for good.
                </p>
                <DeleteProcess project={p} />
              </div>
            </Panel>
          </div>
        )}
      </div>
    </Page>
  )
}
