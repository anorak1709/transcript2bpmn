import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MoreHorizontal } from "lucide-react"
import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
import { ConflictPoint, PolicyDifference } from "@/components/conflict-card"
import { PageHeader, Section, StatusMark } from "@/components/dossier"
import { AddFiles, Gaps, Signoffs, Speakers } from "@/components/process-file"
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
    <tr className="border-b border-hairline align-baseline">
      <td className="max-w-0 py-2.5 pr-3">
        <div className="flex items-baseline gap-2">
          <span className="serif text-graphite" aria-hidden>
            ¶
          </span>
          <span className="truncate" title={t.filename}>
            {t.filename}
          </span>
        </div>
        {/* the side column is narrow: details go under the name instead of in columns */}
        <p className="tabular ml-4 hidden text-xs whitespace-nowrap text-graphite lg:block">
          {t.segment_count != null ? `${t.segment_count} lines` : formatDuration(t.duration_seconds)}
          {t.created_at ? ` · ${formatDay(t.created_at)}` : ""}
        </p>
        {job?.status === "failed" && job.error && (
          <p className="mt-0.5 ml-4 line-clamp-2 text-xs text-graphite">{job.error}</p>
        )}
      </td>
      <td className="tabular hidden py-2.5 pr-3 text-sm whitespace-nowrap text-graphite md:table-cell lg:hidden">
        {formatDay(t.created_at)}
      </td>
      <td className="tabular hidden py-2.5 pr-3 text-sm whitespace-nowrap text-graphite sm:table-cell lg:hidden">
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
            <DropdownMenuItem disabled={!canProcess} onSelect={() => process.mutate()}>
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
      <AlertDialogContent className="bg-sheet">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-2xl">Delete “{project.name}”?</AlertDialogTitle>
          <AlertDialogDescription className="text-graphite">
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
  const run = (format: "bpmn" | "svg" | "png" | "md") =>
    downloadExport(mapId, format).catch((e: Error) => toast.error(e.message))
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline">Export</Button>
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

export function ProjectPage() {
  const { projectId = "" } = useParams()
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
  const resolve = async (id: string, how: Resolution) => {
    try {
      await api.resolveConflict(id, how)
      toast.success("option" in how || "variant" in how ? "Applied to the map" : "Marked as settled")
      await Promise.all(["conflicts", "project", "gaps"].map((k) => qc.invalidateQueries({ queryKey: [k, projectId] })))
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (project.isPending) {
    return (
      <Page>
        <Skeleton className="mb-10 h-16 w-2/3 rounded-sm bg-paper-shade" />
        <Skeleton className="h-64 rounded-sm bg-paper-shade" />
      </Page>
    )
  }
  if (project.error) {
    return (
      <Page>
        <PageHeader eyebrow="Process file" title="Not found" />
        <p className="text-graphite">
          It may have been deleted, or it belongs to another workspace.{" "}
          <Link to="/projects" className="text-ink underline">
            Back to the index
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

  return (
    <Page>
      <PageHeader
        eyebrow={
          <Link to="/projects" className="hover:text-ink">
            ← Index of processes
          </Link>
        }
        title={p.name}
        revision={
          <>
            {countOf(meetings.length, "meeting")}
            {policies.length ? ` · ${countOf(policies.length, "policy document").toLowerCase()}` : ""}
            {p.revised_at ? ` · revised ${formatDay(p.revised_at)}` : ""}
            {p.map_version ? ` · v${p.map_version}` : ""}
            {p.retention_days ? ` · meeting content kept ${p.retention_days} days` : ""}
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

      <div className="grid gap-x-14 gap-y-12 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-12">
          <Section
            title="Points of disagreement"
            id="disagreements"
            aside={points.length ? `${points.length} open` : undefined}
          >
            {!p.merged_map_id ? (
              <p className="py-2 text-sm text-graphite">Listed here once a second meeting is merged.</p>
            ) : conflicts.isPending ? (
              <Skeleton className="h-24 rounded-sm bg-paper-shade" />
            ) : points.length ? (
              <div className="divide-y divide-hairline">
                {points.map((c, i) => (
                  <ConflictPoint key={c.id} number={i + 1} conflict={c} onResolve={(how) => resolve(c.id, how)} />
                ))}
              </div>
            ) : (
              <p className="serif py-2 text-[1.05rem] text-graphite italic">The meetings agree. Nothing to settle.</p>
            )}
          </Section>

          {policies.length > 0 && (
            <Section
              title="Against the policy"
              id="policy"
              aside={differences.length ? `${differences.length} open` : undefined}
            >
              {differences.length ? (
                <div className="divide-y divide-hairline">
                  {differences.map((c, i) => (
                    <PolicyDifference key={c.id} number={i + 1} conflict={c} onResolve={(how) => resolve(c.id, how)} />
                  ))}
                </div>
              ) : (
                <p className="serif py-2 text-[1.05rem] text-graphite italic">
                  {processing ? "Comparing…" : "What people said matches the policy."}
                </p>
              )}
            </Section>
          )}

          {p.merged_map_id && (
            <Section title="Gaps" id="gaps" aside="What nobody said">
              <Gaps projectId={p.id} refresh={refresh} />
            </Section>
          )}
        </div>

        <div className="min-w-0 space-y-12">
          <Section
            title="Meetings"
            id="meetings"
            aside={
              <span aria-live="polite">
                {processing ? `Processing ${countOf(processing, "file").toLowerCase()}…` : "Merged into one map"}
              </span>
            }
          >
            {meetings.length === 0 ? (
              <p className="measure py-4 text-graphite">
                No meetings yet. Add a transcript or recording and the first draft of the map is made from it.
              </p>
            ) : (
              <FileTable files={meetings} projectId={p.id} caption="Meetings in this process" />
            )}
            <AddFiles
              project={p}
              purpose="meeting"
              accept={ACCEPTED_UPLOADS}
              prompt="Drop a recording or transcript to add it."
              hint=".vtt .srt .txt .docx or .mp3 .m4a .wav .webm .mp4 · processing starts on its own"
            />
          </Section>

          <Section title="Policy documents" id="policy-documents" aside="Compared, never merged">
            {policies.length > 0 && <FileTable files={policies} projectId={p.id} caption="Policy documents" />}
            <AddFiles
              project={p}
              purpose="policy"
              accept=".docx,.txt"
              prompt="Add the written SOP or policy to check the map against it."
              hint=".docx or .txt · differences are listed under “Against the policy”"
            />
          </Section>

          <Section title="Speakers" id="speakers" aside="Tag each person's role once">
            <Speakers projectId={p.id} refresh={merged} />
          </Section>
        </div>
      </div>

      {p.merged_map_id && (
        <Section title="Sign-off" id="signoff" className="mt-12" aside="Each person confirms their part">
          <Signoffs project={p} />
        </Section>
      )}

      <footer className="mt-20 flex flex-wrap items-center justify-between gap-4 border-t border-hairline pt-5">
        <p className="text-sm text-graphite">
          Withdrawing a process deletes its recordings, transcripts and maps for good.
        </p>
        <WithdrawFile project={p} />
      </footer>
    </Page>
  )
}
