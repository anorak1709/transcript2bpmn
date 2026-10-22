import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, Check, ChevronDown, MoreHorizontal } from "lucide-react"
import { useEffect, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
import { ConflictPoint, PolicyDifference } from "@/components/conflict-card"
import { PageHeader, Section, StatusMark } from "@/components/dossier"
import { AddFiles, Signoffs, Speakers } from "@/components/process-file"
import { Improvements, ReviewQueue } from "@/components/review-tools"
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
import { type Conflict, type Gap, isActive, type Project, type Resolution, type Transcript } from "@/lib/types"
import { cn } from "@/lib/utils"

function MeetingRow({ t, projectId }: { t: Transcript; projectId: string }) {
  const qc = useQueryClient()
  const process = useMutation({
    mutationFn: () => api.process(t.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["project", projectId] }),
    onError: (e) => toast.error(e.message),
  })
  const job = t.latest_job
  const canProcess = !t.content_expired && !isActive(job)
  return (
    <tr className="border-b border-line align-baseline">
      <td className="max-w-0 py-2.5 pr-3">
        <div className="flex items-baseline gap-2">
          <span className="text-fg-muted" aria-hidden>
            ¶
          </span>
          <span className="truncate" title={t.filename}>
            {t.filename}
          </span>
        </div>
        {/* the side column is narrow: details go under the name instead of in columns */}
        <p className="tabular ml-4 hidden text-xs whitespace-nowrap text-fg-muted lg:block">
          {t.segment_count != null ? `${t.segment_count} lines` : formatDuration(t.duration_seconds)}
          {t.created_at ? ` · ${formatDay(t.created_at)}` : ""}
        </p>
        {job?.status === "failed" && job.error && (
          <p className="mt-0.5 ml-4 line-clamp-2 text-xs text-fg-muted">{job.error}</p>
        )}
      </td>
      <td className="tabular hidden py-2.5 pr-3 text-sm whitespace-nowrap text-fg-muted md:table-cell lg:hidden">
        {formatDay(t.created_at)}
      </td>
      <td className="tabular hidden py-2.5 pr-3 text-sm whitespace-nowrap text-fg-muted sm:table-cell lg:hidden">
        {t.segment_count != null ? `${t.segment_count} lines` : formatDuration(t.duration_seconds)}
      </td>
      <td className="w-28 py-2.5 pr-1" aria-live="polite">
        <StatusMark job={job} expired={t.content_expired} />
      </td>
      <td className="w-10 py-1 text-right">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={`Actions for ${t.filename}`}>
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
            {t.live_status === "recording" && (
              <DropdownMenuItem
                onSelect={() =>
                  api.finishLive(t.id).then(
                    () => qc.invalidateQueries({ queryKey: ["project", projectId] }),
                    (e: Error) => toast.error(e.message),
                  )
                }
              >
                Finish this live interview
              </DropdownMenuItem>
            )}
            <DropdownMenuItem disabled={!canProcess || t.live_status === "recording"} onSelect={() => process.mutate()}>
              {job ? "Process again" : "Process"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </td>
    </tr>
  )
}

function WithdrawFile({ project }: { project: Project }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [typed, setTyped] = useState("")
  const del = useMutation({
    mutationFn: () => api.deleteProject(project.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] })
      toast.success(`Deleted "${project.name}"`)
      navigate("/projects")
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <AlertDialog onOpenChange={() => setTyped("")}>
      <AlertDialogTrigger asChild>
        <Button variant="destructive" size="sm">
          Delete this process…
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent className="bg-surface">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-2xl">Delete “{project.name}”?</AlertDialogTitle>
          <AlertDialogDescription className="text-fg-muted">
            Every recording, transcript, map and version in this file is permanently deleted. The audit log keeps a
            record that it happened. This can't be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-2">
          <label htmlFor="confirm-name" className="label block">
            Type the process name to confirm
          </label>
          <Input id="confirm-name" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep it</AlertDialogCancel>
          <AlertDialogAction
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

function FileTable({ files, projectId, caption }: { files: Transcript[]; projectId: string; caption: string }) {
  return (
    <table className="w-full table-fixed text-[0.95rem]">
      <caption className="sr-only">{caption}</caption>
      <thead className="sr-only">
        <tr>
          <th>File</th>
          <th>Added</th>
          <th>Length</th>
          <th>Status</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {files.map((t) => (
          <MeetingRow key={t.id} t={t} projectId={projectId} />
        ))}
      </tbody>
    </table>
  )
}

export function ExportMenu({ mapId }: { mapId: string }) {
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: api.integrations, staleTime: 300_000 })
  const run = (format: "bpmn" | "svg" | "png" | "md" | "docx" | "pdf") =>
    downloadExport(mapId, format).catch((e: Error) => toast.error(e.message))
  const camunda = () =>
    api.pushCamunda(mapId).then(
      (r) =>
        toast.success("Sent to Camunda", { action: { label: "Open", onClick: () => window.open(r.url, "_blank") } }),
      (e: Error) => toast.error(e.message),
    )
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline">Export</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => run("bpmn")}>BPMN 2.0 file</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("docx")}>Written procedure (Word)</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("pdf")}>Written procedure (PDF)</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("md")}>Written procedure (Markdown)</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("png")}>Diagram image (PNG)</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("svg")}>Diagram vector (SVG)</DropdownMenuItem>
        {integrations.data?.camunda && (
          <DropdownMenuItem onSelect={() => void camunda()}>Send to Camunda</DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

const STEPS = ["meetings", "review", "improve", "share"] as const
type Step = (typeof STEPS)[number]
const STEP_LABEL: Record<Step, string> = { meetings: "Meetings", review: "Review", improve: "Improve", share: "Share" }

/** "Who does 'Pay supplier'? The existing map says…" -> "Who does 'Pay supplier'?" */
function question(description: string): string {
  const m = /^(.+?\?)(?=\s+(?:The|Existing|Policy|Meetings|They)\b)/.exec(description)
  return m ? m[1] : description
}

type ReviewItem =
  | { key: string; kind: "disagreement"; conflict: Conflict; n: number }
  | { key: string; kind: "policy"; conflict: Conflict; n: number }
  | { key: string; kind: "gap"; gap: Gap }

const KIND_WORD = { disagreement: "Meetings disagree", policy: "Against the policy", gap: "Nobody said" }

function NextStep({ to, onGo }: { to: Step | null; onGo: (s: Step) => void }) {
  if (!to) return null
  return (
    <div className="mt-14 flex justify-end border-t border-line pt-6">
      <Button variant="outline" onClick={() => onGo(to)}>
        Next: {STEP_LABEL[to]} <ArrowRight aria-hidden />
      </Button>
    </div>
  )
}

/** The process as four guided steps: Meetings → Review → Improve → Share. One step on screen at
 *  a time; the page opens on the first one that needs you (MASTER: guided steps). */
export function ProjectPage() {
  const { projectId = "" } = useParams()
  const [params, setParams] = useSearchParams()
  const qc = useQueryClient()
  const [open, setOpen] = useState<string | null>(null)
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.project(projectId),
    // Poll while anything is processing; stop when everything has settled.
    refetchInterval: (q) => (q.state.data?.transcripts.some((t) => isActive(t.latest_job)) ? 2000 : false),
  })
  const merged = project.data?.transcripts.filter((t) => t.latest_job?.status === "done").length ?? 0
  const refresh = `${merged}:${project.data?.map_version ?? 0}`
  const hasMap = !!project.data?.merged_map_id
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: api.integrations, staleTime: 300_000 })
  const conflicts = useQuery({
    queryKey: ["conflicts", projectId, refresh],
    queryFn: () => api.conflicts(projectId, { status: "open" }),
    enabled: hasMap,
  })
  const gaps = useQuery({ queryKey: ["gaps", projectId, refresh], queryFn: () => api.gaps(projectId), enabled: hasMap })
  const ideas = useQuery({
    queryKey: ["improvements", project.data?.merged_map_id, refresh],
    queryFn: () => api.improvements(project.data!.merged_map_id!),
    enabled: hasMap,
  })
  const signoffs = useQuery({ queryKey: ["signoffs", projectId], queryFn: () => api.signoffs(projectId) })
  const dismiss = useMutation({
    mutationFn: (id: string) => api.dismissGap(projectId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["gaps", projectId] }),
    onError: (e) => toast.error(e.message),
  })

  const resolve = async (id: string, how: Resolution) => {
    try {
      await api.resolveConflict(id, how)
      toast.success("option" in how || "variant" in how ? "Applied to the map" : "Marked as settled")
      setOpen(null)
      await Promise.all(["conflicts", "project", "gaps"].map((k) => qc.invalidateQueries({ queryKey: [k, projectId] })))
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  // Open on the first step that needs you, then pin it in the URL so polling never moves you.
  const ready = project.data && signoffs.data && (!hasMap || (conflicts.data && gaps.data))
  const opening: Step | null = !ready
    ? null
    : !hasMap || !project.data!.transcripts.some((t) => t.purpose === "meeting")
      ? "meetings"
      : conflicts.data!.length + gaps.data!.length
        ? "review"
        : signoffs.data!.some((x) => x.status === "changes_requested")
          ? "share"
          : "improve"
  useEffect(() => {
    if (opening && !params.get("step")) setParams({ step: opening }, { replace: true })
  }, [opening, params, setParams])

  if (project.isPending) {
    return (
      <Page>
        <Skeleton className="mb-10 h-20 w-2/3 rounded-sm bg-raised" />
        <Skeleton className="h-64 rounded-sm bg-raised" />
      </Page>
    )
  }
  if (project.error) {
    return (
      <Page>
        <PageHeader eyebrow="Process" title="Not found" />
        <p className="text-fg-muted">
          It may have been deleted, or it belongs to another workspace.{" "}
          <Link to="/projects" className="text-fg underline">
            Back to processes
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
  const items: ReviewItem[] = [
    ...points.map((c, i) => ({ key: c.id, kind: "disagreement" as const, conflict: c, n: i + 1 })),
    ...differences.map((c, i) => ({ key: c.id, kind: "policy" as const, conflict: c, n: i + 1 })),
    ...(gaps.data ?? []).map((g) => ({ key: g.id, kind: "gap" as const, gap: g })),
  ]
  const waiting = (signoffs.data ?? []).filter((s) => s.status === "pending").length
  const changes = (signoffs.data ?? []).filter((s) => s.status === "changes_requested").length

  // Each step's state, shown in the step bar.
  const status: Record<Step, { text: string; needs: boolean; done: boolean }> = {
    meetings: processing
      ? { text: `Processing ${processing}…`, needs: false, done: false }
      : meetings.length
        ? { text: countOf(meetings.length, "meeting"), needs: false, done: true }
        : { text: "Add a meeting", needs: true, done: false },
    review: !hasMap
      ? { text: "Not started", needs: false, done: false }
      : items.length
        ? { text: `${items.length} need${items.length === 1 ? "s" : ""} you`, needs: true, done: false }
        : { text: "All settled", needs: false, done: true },
    improve: !hasMap
      ? { text: "Not started", needs: false, done: false }
      : {
          text: ideas.data?.length ? countOf(ideas.data.length, "idea").toLowerCase() : "No ideas",
          needs: false,
          done: false,
        },
    share: changes
      ? { text: `${changes} asked for changes`, needs: true, done: false }
      : waiting
        ? { text: `${waiting} awaiting`, needs: false, done: false }
        : { text: signoffs.data?.length ? "Signed off" : "Not shared", needs: false, done: !!signoffs.data?.length },
  }
  const requested = params.get("step") as Step | null
  const step: Step = requested && STEPS.includes(requested) ? requested : (opening ?? "meetings")
  const go = (s: Step) => {
    setParams({ step: s }, { replace: true })
    setOpen(null)
    window.scrollTo({ top: 0 })
  }

  return (
    <Page>
      <PageHeader
        eyebrow={
          <Link to="/projects" className="hover:text-fg">
            ← Processes
          </Link>
        }
        title={p.name}
        revision={
          <>
            {countOf(meetings.length, "meeting")}
            {policies.length ? ` · ${countOf(policies.length, "policy document").toLowerCase()}` : ""}
            {p.map_version ? ` · map v${p.map_version}` : ""}
            {p.revised_at ? ` · revised ${formatDay(p.revised_at)}` : ""}
          </>
        }
        actions={
          p.merged_map_id && (
            <Button asChild>
              <Link to={`/maps/${p.merged_map_id}`}>Open the map</Link>
            </Button>
          )
        }
      />

      <nav aria-label="Steps" className="mb-12">
        <ol className="grid grid-cols-2 gap-px overflow-hidden border border-line bg-line sm:grid-cols-4">
          {STEPS.map((s, i) => {
            const st = status[s]
            const current = s === step
            return (
              <li key={s} className="bg-bg">
                <button
                  type="button"
                  onClick={() => go(s)}
                  aria-current={current ? "step" : undefined}
                  className={cn(
                    "transition-quiet flex h-full w-full flex-col items-start gap-1 border-t-4 px-4 py-4 text-left hover:bg-surface",
                    current ? "border-signal bg-surface" : "border-transparent",
                  )}
                >
                  <span className="flex items-center gap-2 font-heading text-lg font-semibold">
                    <span
                      className={cn(
                        "tabular inline-flex size-6 items-center justify-center text-sm",
                        st.done
                          ? "bg-fg text-bg"
                          : current
                            ? "bg-signal text-bg"
                            : "border border-line-strong text-fg-muted",
                      )}
                      aria-hidden
                    >
                      {st.done ? <Check className="size-4" strokeWidth={3} /> : i + 1}
                    </span>
                    {STEP_LABEL[s]}
                  </span>
                  <span className={cn("text-sm", st.needs ? "font-semibold text-signal" : "text-fg-muted")}>
                    {st.text}
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
      </nav>

      <div className="max-w-[880px]">
        {step === "meetings" && (
          <div className="space-y-14">
            <Section
              title="Meetings"
              id="meetings"
              aside={
                <span aria-live="polite">
                  {processing ? `Processing ${countOf(processing, "file").toLowerCase()}…` : null}
                </span>
              }
            >
              {meetings.length === 0 && (
                <p className="mb-6 text-lg">Add a transcript or recording to draft the first map.</p>
              )}
              {meetings.length > 0 && (
                <FileTable files={meetings} projectId={p.id} caption="Meetings in this process" />
              )}
              <AddFiles
                project={p}
                purpose="meeting"
                accept={ACCEPTED_UPLOADS}
                prompt="Drop a recording or transcript to add it."
                hint=".vtt .srt .txt .docx or .mp3 .m4a .wav .webm .mp4 · processing starts on its own"
              />
              {integrations.data?.ai && (
                <p className="mt-4">
                  <Link to={`/projects/${p.id}/live`} className="underline underline-offset-4 hover:text-signal">
                    Or record a live interview
                  </Link>{" "}
                  <span className="text-fg-muted">: the draft updates every few minutes.</span>
                </p>
              )}
            </Section>
            <Section title="Policy documents" id="policies" aside="Compared with the map, never merged">
              {policies.length > 0 && <FileTable files={policies} projectId={p.id} caption="Policy documents" />}
              <AddFiles
                project={p}
                purpose="policy"
                accept=".docx,.txt"
                prompt="Add the written SOP or policy to check the map against it."
                hint=".docx or .txt · differences appear in Review"
              />
            </Section>
            {meetings.length > 0 && (
              <Section title="Speakers" id="speakers" aside="Tag each person's role once">
                <Speakers projectId={p.id} refresh={merged} />
              </Section>
            )}
            <NextStep to={hasMap ? "review" : null} onGo={go} />
          </div>
        )}

        {step === "review" && (
          <div>
            {!hasMap ? (
              <p className="text-lg text-fg-muted">Add a meeting first: there's nothing to review yet.</p>
            ) : (
              <>
                <h2 className="text-[1.75rem]">
                  {items.length
                    ? `${items.length} thing${items.length === 1 ? "" : "s"} need${items.length === 1 ? "s" : ""} you`
                    : "Nothing needs you"}
                </h2>
                <p className="mt-2 mb-8 text-fg-muted">
                  {items.length
                    ? "Open one to see who said what and settle it. Settled items leave the list."
                    : "The meetings agree, match the policy and leave no gaps."}
                </p>
                <ul className="border-t border-line">
                  {items.map((it) => {
                    const isOpen = open === it.key
                    const title = it.kind === "gap" ? it.gap.description : question(it.conflict.description)
                    const sub =
                      it.kind === "gap"
                        ? it.gap.question
                        : it.conflict.options.length
                          ? it.conflict.options.join("  or  ")
                          : it.conflict.kind === "missing_step"
                            ? "Only in the policy"
                            : "Only in the meetings"
                    return (
                      <li key={it.key} className="border-b border-line">
                        <button
                          type="button"
                          aria-expanded={isOpen}
                          aria-controls={`item-${it.key}`}
                          onClick={() => setOpen(isOpen ? null : it.key)}
                          className="transition-quiet flex w-full items-start gap-4 py-5 text-left hover:bg-surface sm:px-2"
                        >
                          <span className="min-w-0 flex-1">
                            <span className={cn("label block", it.kind !== "gap" && "text-signal")}>
                              {KIND_WORD[it.kind]}
                            </span>
                            <span className="mt-1 block font-heading text-[1.15rem] leading-snug font-medium">
                              {title}
                            </span>
                            <span className="mt-1 block text-fg-muted">{sub}</span>
                          </span>
                          <ChevronDown
                            className={cn(
                              "mt-6 size-5 shrink-0 text-fg-muted transition-transform",
                              isOpen && "rotate-180",
                            )}
                            aria-hidden
                          />
                        </button>
                        {isOpen && (
                          <div id={`item-${it.key}`} className="pb-6 sm:px-2">
                            {it.kind === "disagreement" ? (
                              <ConflictPoint
                                bare
                                number={it.n}
                                conflict={it.conflict}
                                onResolve={(how) => resolve(it.key, how)}
                              />
                            ) : it.kind === "policy" ? (
                              <PolicyDifference
                                bare
                                number={it.n}
                                conflict={it.conflict}
                                onResolve={(how) => resolve(it.key, how)}
                              />
                            ) : (
                              <div className="flex flex-wrap items-center gap-3">
                                <p className="flex-1 text-fg-muted">
                                  Add the missing part in the map, or tell us it isn't a gap.
                                </p>
                                <Button asChild variant="outline" size="sm">
                                  <Link to={`/maps/${p.merged_map_id}`}>Fix in the map</Link>
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  disabled={dismiss.isPending}
                                  onClick={() => dismiss.mutate(it.gap.id)}
                                >
                                  Not a gap
                                </Button>
                              </div>
                            )}
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ul>

                <details className="group mt-12">
                  <summary className="flex items-center gap-2 py-2 font-heading text-lg font-medium [&::-webkit-details-marker]:hidden">
                    <ChevronDown
                      className="size-5 -rotate-90 text-fg-muted transition-transform group-open:rotate-0"
                      aria-hidden
                    />
                    Check the AI's draft, step by step
                  </summary>
                  <div className="mt-3">
                    <ReviewQueue mapId={p.merged_map_id!} limit={8} key={refresh} />
                  </div>
                </details>
              </>
            )}
            <NextStep to="improve" onGo={go} />
          </div>
        )}

        {step === "improve" && (
          <div>
            <h2 className="text-[1.75rem]">Where the process could be better</h2>
            <p className="mt-2 mb-8 text-fg-muted">
              Read from the map's shape: work done by hand, handoffs, approvals.
            </p>
            {hasMap ? (
              <Improvements mapId={p.merged_map_id!} aiAvailable={!!integrations.data?.ai} key={refresh} />
            ) : (
              <p className="text-fg-muted">Ideas appear once there's a map.</p>
            )}
            <NextStep to="share" onGo={go} />
          </div>
        )}

        {step === "share" && (
          <div className="space-y-14">
            <Section title="Sign-off" id="signoff" aside="Each person confirms their part">
              {hasMap ? <Signoffs project={p} /> : <p className="text-fg-muted">Available once there's a map.</p>}
            </Section>
            {p.merged_map_id && (
              <Section title="Take it with you" id="exports">
                <div className="flex flex-wrap gap-2">
                  <ExportMenu mapId={p.merged_map_id} />
                  <Button
                    variant="outline"
                    onClick={() => downloadAgenda(p.id).catch((e: Error) => toast.error(e.message))}
                  >
                    Next meeting's agenda
                  </Button>
                </div>
              </Section>
            )}
            <div className="flex flex-wrap items-center justify-between gap-4 border-t border-line pt-6">
              <p className="text-sm text-fg-muted">
                Deleting a process removes its recordings, transcripts and maps for good.
              </p>
              <WithdrawFile project={p} />
            </div>
          </div>
        )}
      </div>
    </Page>
  )
}
