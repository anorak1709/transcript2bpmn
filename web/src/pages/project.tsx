import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowLeft,
  Download,
  FileAudio,
  FileText,
  Loader2,
  MoreHorizontal,
  Play,
  RotateCw,
  Trash2,
  Upload,
  Workflow,
} from "lucide-react"
import { useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
import { ConflictCard } from "@/components/conflict-card"
import { EmptyState } from "@/components/empty-state"
import { JobBadge } from "@/components/status"
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, downloadExport } from "@/lib/api"
import { ACCEPTED_UPLOADS, AUDIO_EXTENSIONS, formatDate, formatDuration } from "@/lib/format"
import { isActive, type Project, type Transcript } from "@/lib/types"
import { cn } from "@/lib/utils"

const isAudio = (name: string) => AUDIO_EXTENSIONS.some((ext) => name.toLowerCase().endsWith(ext))

function UploadZone({ project }: { project: Project }) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState<string[]>([])

  async function handle(files: FileList | null) {
    if (!files?.length) return
    const list = Array.from(files)
    setUploading(list.map((f) => f.name))
    for (const file of list) {
      try {
        const t = await api.upload(project.id, file)
        await api.process(t.id) // upload and process in one step: that's what people want
        toast.success(`${file.name} uploaded`, { description: "Processing has started." })
      } catch (e) {
        toast.error(`${file.name}: ${(e as Error).message}`)
      }
      setUploading((u) => u.filter((n) => n !== file.name))
    }
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
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-8 text-center transition-colors",
        dragging ? "border-primary bg-accent" : "bg-muted/30",
      )}
    >
      <Upload className="size-6 text-muted-foreground" aria-hidden />
      <div className="space-y-1">
        <p className="text-sm font-medium">Drop meeting files here</p>
        <p className="text-xs text-muted-foreground">
          Transcripts (.vtt, .srt, .txt, .docx) or recordings (.mp3, .m4a, .wav, .webm, .mp4). Processing starts
          automatically.
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
      <Button asChild variant="outline" size="sm" disabled={uploading.length > 0}>
        <label htmlFor="upload-input" className="cursor-pointer">
          {uploading.length ? <Loader2 className="animate-spin" aria-hidden /> : <Upload aria-hidden />}
          {uploading.length ? `Uploading ${uploading[0]}…` : "Choose files"}
        </label>
      </Button>
    </div>
  )
}

function TranscriptRow({ t, projectId }: { t: Transcript; projectId: string }) {
  const qc = useQueryClient()
  const process = useMutation({
    mutationFn: () => api.process(t.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["project", projectId] }),
    onError: (e) => toast.error(e.message),
  })
  const job = t.latest_job
  const canProcess = !t.content_expired && !isActive(job)
  const Icon = isAudio(t.filename) ? FileAudio : FileText

  return (
    <TableRow>
      <TableCell className="max-w-[260px]">
        <div className="flex items-center gap-2">
          <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate font-medium" title={t.filename}>
            {t.filename}
          </span>
        </div>
        {job?.status === "failed" && job.error && (
          <p className="mt-1 line-clamp-2 text-xs text-destructive">{job.error}</p>
        )}
      </TableCell>
      <TableCell className="hidden text-muted-foreground md:table-cell">{formatDate(t.created_at)}</TableCell>
      <TableCell className="hidden text-muted-foreground sm:table-cell">
        {t.segment_count != null ? `${t.segment_count} lines` : formatDuration(t.duration_seconds)}
      </TableCell>
      <TableCell>
        <JobBadge job={job} expired={t.content_expired} />
      </TableCell>
      <TableCell className="text-right">
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
                  <Workflow aria-hidden /> Open this meeting's map
                </Link>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem disabled={!canProcess} onSelect={() => process.mutate()}>
              {job ? <RotateCw aria-hidden /> : <Play aria-hidden />}
              {job ? "Process again" : "Process"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
  )
}

function DeleteProject({ project }: { project: Project }) {
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
        <Button variant="ghost" className="text-destructive hover:text-destructive">
          <Trash2 aria-hidden /> Delete
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this project?</AlertDialogTitle>
          <AlertDialogDescription>
            Every meeting file, transcript, map and version in "{project.name}" is permanently deleted. This can't be
            undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-2">
          <Label htmlFor="confirm-name">Type the project name to confirm</Label>
          <Input id="confirm-name" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={typed !== project.name || del.isPending}
            onClick={(e) => {
              e.preventDefault()
              del.mutate()
            }}
            className="bg-destructive text-white hover:bg-destructive/90"
          >
            {del.isPending && <Loader2 className="animate-spin" aria-hidden />}
            Delete project
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function ExportMenu({ mapId, label = "Export" }: { mapId: string; label?: string }) {
  const run = (format: "bpmn" | "svg" | "png" | "md") =>
    downloadExport(mapId, format).catch((e: Error) => toast.error(e.message))
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline">
          <Download aria-hidden /> {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => run("bpmn")}>BPMN 2.0 (.bpmn)</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("png")}>Image (.png)</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("svg")}>Vector image (.svg)</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => run("md")}>Written procedure (.md)</DropdownMenuItem>
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
      toast.success(option == null ? "Marked as resolved" : "Applied to the map")
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
      <Page title={<Skeleton className="h-8 w-64" />}>
        <Skeleton className="h-64 rounded-xl" />
      </Page>
    )
  }
  if (project.error) {
    return (
      <Page title="Project not found">
        <p className="text-sm text-muted-foreground">
          It may have been deleted, or it belongs to another workspace.{" "}
          <Link to="/projects" className="underline">
            Back to projects
          </Link>
        </p>
      </Page>
    )
  }
  const p = project.data
  const processing = p.transcripts.filter((t) => isActive(t.latest_job)).length

  return (
    <Page
      title={p.name}
      description={
        <>
          <Link to="/projects" className="mr-2 inline-flex items-center gap-1 hover:underline">
            <ArrowLeft className="size-3" aria-hidden /> Projects
          </Link>
          {p.transcripts.length} meeting{p.transcripts.length === 1 ? "" : "s"}
          {p.retention_days ? ` · meeting content deleted after ${p.retention_days} days` : ""}
        </>
      }
      actions={
        <>
          {p.merged_map_id && (
            <>
              <ExportMenu mapId={p.merged_map_id} />
              <Button asChild>
                <Link to={`/maps/${p.merged_map_id}`}>
                  <Workflow aria-hidden /> Open map
                </Link>
              </Button>
            </>
          )}
          <DeleteProject project={p} />
        </>
      }
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <UploadZone project={p} />
          <Card>
            <CardHeader>
              <CardTitle asChild className="text-base">
                <h2>Meetings</h2>
              </CardTitle>
              <CardDescription aria-live="polite">
                {processing
                  ? `Processing ${processing} meeting${processing === 1 ? "" : "s"}…`
                  : "Each processed meeting is merged into the project map."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {p.transcripts.length === 0 ? (
                <EmptyState icon={FileText} title="No meetings yet">
                  Upload a transcript or recording above to build the first version of the map.
                </EmptyState>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>File</TableHead>
                      <TableHead className="hidden md:table-cell">Added</TableHead>
                      <TableHead className="hidden sm:table-cell">Length</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="w-12">
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {p.transcripts.map((t) => (
                      <TranscriptRow key={t.id} t={t} projectId={p.id} />
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle asChild className="text-base">
              <h2>Disagreements to review</h2>
            </CardTitle>
            <CardDescription>
              Where meetings describe the process differently. Nothing is decided for you.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {!p.merged_map_id ? (
              <p className="text-sm text-muted-foreground">Appears once a second meeting is merged.</p>
            ) : conflicts.isPending ? (
              <Skeleton className="h-24" />
            ) : conflicts.data?.length ? (
              conflicts.data.map((c) => (
                <ConflictCard
                  key={c.id}
                  kind={c.kind}
                  description={c.description}
                  options={c.options}
                  onResolve={(opt) => resolve(c.id, opt)}
                />
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No open disagreements.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
