import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MoreHorizontal } from "lucide-react"
import { useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
import { ConflictPoint } from "@/components/conflict-card"
import { PageHeader, Section, StatusMark } from "@/components/dossier"
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
import { api, downloadExport } from "@/lib/api"
import { ACCEPTED_UPLOADS, countOf, formatDay, formatDuration } from "@/lib/format"
import { isActive, type Project, type Transcript } from "@/lib/types"
import { cn } from "@/lib/utils"

function AddMeetings({ project }: { project: Project }) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState<string | null>(null)

  async function handle(files: FileList | null) {
    if (!files?.length) return
    for (const file of Array.from(files)) {
      setUploading(file.name)
      try {
        const t = await api.upload(project.id, file)
        await api.process(t.id) // upload and process in one step: that's what people want
        toast.success(`${file.name} uploaded`, { description: "Processing has started." })
      } catch (e) {
        toast.error(`${file.name}: ${(e as Error).message}`)
      }
    }
    setUploading(null)
    qc.invalidateQueries({ queryKey: ["project", project.id] })
    if (input.current) input.current.value = ""
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        void handle(e.dataTransfer.files)
      }}
      className={cn(
        "transition-quiet mt-4 flex flex-wrap items-center justify-between gap-3 rounded-sm border border-dashed px-4 py-4",
        dragging ? "border-ink bg-paper-shade" : "border-rule",
      )}
    >
      <div>
        <p className="serif text-[1.05rem] italic">Drop a recording or transcript to add it.</p>
        <p className="text-xs text-graphite">
          .vtt .srt .txt .docx or .mp3 .m4a .wav .webm .mp4 · processing starts on its own
        </p>
      </div>
      <input
        ref={input}
        id="upload-input"
        type="file"
        multiple
        accept={ACCEPTED_UPLOADS}
        className="sr-only"
        onChange={(e) => void handle(e.target.files)}
      />
      <Button asChild variant="outline" size="sm" disabled={!!uploading}>
        <label htmlFor="upload-input" className="cursor-pointer">
          {uploading ? `Uploading ${uploading}…` : "Choose files"}
        </label>
      </Button>
    </div>
  )
}

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
        {job?.status === "failed" && job.error && (
          <p className="mt-0.5 ml-4 line-clamp-2 text-xs text-graphite">{job.error}</p>
        )}
      </td>
      <td className="tabular hidden py-2.5 pr-3 text-sm whitespace-nowrap text-graphite md:table-cell">
        {formatDay(t.created_at)}
      </td>
      <td className="tabular hidden py-2.5 pr-3 text-sm whitespace-nowrap text-graphite sm:table-cell">
        {t.segment_count != null ? `${t.segment_count} lines` : formatDuration(t.duration_seconds)}
      </td>
      <td className="py-2.5 pr-1" aria-live="polite">
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
                <Link to={`/maps/${job.map_id}`}>Open this meeting's own map</Link>
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
  // Refetch disagreements whenever another meeting finishes merging.
  const merged = project.data?.transcripts.filter((t) => t.latest_job?.status === "done").length ?? 0
  const conflicts = useQuery({
    queryKey: ["conflicts", projectId, merged],
    queryFn: () => api.conflicts(projectId, "open"),
    enabled: !!project.data?.merged_map_id,
  })
  const resolve = async (id: string, option: number | null) => {
    try {
      await api.resolveConflict(id, option)
      toast.success(option == null ? "Marked as settled" : "Applied to the map")
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["conflicts", projectId] }),
        qc.invalidateQueries({ queryKey: ["project", projectId] }),
      ])
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
  const processing = p.transcripts.filter((t) => isActive(t.latest_job)).length
  const points = conflicts.data ?? []

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
            {countOf(p.transcripts.length, "meeting")}
            {p.revised_at ? ` · revised ${formatDay(p.revised_at)}` : ""}
            {p.map_version ? ` · v${p.map_version}` : ""}
            {p.retention_days ? ` · meeting content kept ${p.retention_days} days` : ""}
          </>
        }
        actions={
          p.merged_map_id && (
            <>
              <ExportMenu mapId={p.merged_map_id} />
              <Button asChild>
                <Link to={`/maps/${p.merged_map_id}`}>Open the map</Link>
              </Button>
            </>
          )
        }
      />

      <div className="grid gap-x-14 gap-y-12 lg:grid-cols-[minmax(0,1fr)_400px]">
        <Section
          title="Meetings"
          id="meetings"
          aside={
            <span aria-live="polite">
              {processing ? `Processing ${countOf(processing, "meeting").toLowerCase()}…` : "Merged into one map"}
            </span>
          }
        >
          {p.transcripts.length === 0 ? (
            <p className="measure py-4 text-graphite">
              No meetings yet. Add a transcript or recording and the first draft of the map is made from it.
            </p>
          ) : (
            <table className="w-full table-fixed text-[0.95rem]">
              <caption className="sr-only">Meetings in this process</caption>
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
                {p.transcripts.map((t) => (
                  <MeetingRow key={t.id} t={t} projectId={p.id} />
                ))}
              </tbody>
            </table>
          )}
          <AddMeetings project={p} />
        </Section>

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
                <ConflictPoint
                  key={c.id}
                  number={i + 1}
                  kind={c.kind}
                  description={c.description}
                  options={c.options}
                  onResolve={(opt) => resolve(c.id, opt)}
                />
              ))}
            </div>
          ) : (
            <p className="serif py-2 text-[1.05rem] text-graphite italic">The meetings agree. Nothing to settle.</p>
          )}
        </Section>
      </div>

      <footer className="mt-20 flex flex-wrap items-center justify-between gap-4 border-t border-hairline pt-5">
        <p className="text-sm text-graphite">
          Withdrawing a process deletes its recordings, transcripts and maps for good.
        </p>
        <WithdrawFile project={p} />
      </footer>
    </Page>
  )
}
