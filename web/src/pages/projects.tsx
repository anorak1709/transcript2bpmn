import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FileAudio, FolderKanban, GitCompareArrows, Loader2, Plus, Workflow } from "lucide-react"
import { useState } from "react"
import { Link, useNavigate } from "react-router"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
import { EmptyState } from "@/components/empty-state"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"

function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState("")
  const [retention, setRetention] = useState("")
  const create = useMutation({
    mutationFn: () => api.createProject(name.trim(), retention ? Number(retention) : null),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] })
      onOpenChange(false)
      setName("")
      setRetention("")
      navigate(`/projects/${p.id}`)
    },
    onError: (e) => toast.error(String(e.message)),
  })
  const retentionInvalid = retention !== "" && !(Number.isInteger(Number(retention)) && Number(retention) >= 1)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden /> New project
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim() && !retentionInvalid) create.mutate()
          }}
          className="space-y-5"
        >
          <DialogHeader>
            <DialogTitle>New project</DialogTitle>
            <DialogDescription>
              A project collects every meeting about one process and merges them into a single map.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="project-name">Process name</Label>
            <Input
              id="project-name"
              placeholder="e.g. Supplier invoice approval"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={255}
              required
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="project-retention">Delete meeting content after (days)</Label>
            <Input
              id="project-retention"
              inputMode="numeric"
              placeholder="Keep forever"
              value={retention}
              onChange={(e) => setRetention(e.target.value.replace(/[^\d]/g, ""))}
              aria-invalid={retentionInvalid}
              aria-describedby="retention-help"
            />
            <p id="retention-help" className="text-xs text-muted-foreground">
              Uploaded files and transcript text are deleted after this many days. Maps are kept.
            </p>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || retentionInvalid || create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              Create project
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function Projects() {
  const [creating, setCreating] = useState(false)
  const { data, isPending, error } = useQuery({ queryKey: ["projects"], queryFn: api.projects })

  return (
    <Page
      title="Projects"
      description="Each project turns one or more meetings about a process into a single BPMN map."
      actions={<NewProjectDialog open={creating} onOpenChange={setCreating} />}
    >
      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy>
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-36 rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Couldn't load projects: {error.message}
        </p>
      ) : data.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="No projects yet"
          action={
            <Button onClick={() => setCreating(true)}>
              <Plus aria-hidden /> Create your first project
            </Button>
          }
        >
          Create a project, upload a meeting transcript or recording, and get an editable BPMN map.
        </EmptyState>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((p) => (
            <li key={p.id}>
              <Link
                to={`/projects/${p.id}`}
                className="block h-full rounded-xl outline-none transition-shadow hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Card className="h-full">
                  <CardHeader>
                    <CardTitle asChild className="line-clamp-2 text-base">
                      <h2>{p.name}</h2>
                    </CardTitle>
                    <CardDescription>
                      {p.transcripts.length} meeting{p.transcripts.length === 1 ? "" : "s"}
                      {p.retention_days ? ` · content kept ${p.retention_days} days` : ""}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-2">
                    {p.merged_map_id ? (
                      <Badge variant="secondary">
                        <Workflow aria-hidden /> Map ready
                      </Badge>
                    ) : (
                      <Badge variant="outline">
                        <FileAudio aria-hidden /> No map yet
                      </Badge>
                    )}
                    {p.open_conflicts > 0 && (
                      <Badge variant="outline" className="border-amber-500/50 text-amber-700 dark:text-amber-300">
                        <GitCompareArrows aria-hidden /> {p.open_conflicts} to review
                      </Badge>
                    )}
                  </CardContent>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Page>
  )
}
