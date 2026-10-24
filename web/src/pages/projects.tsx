import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight } from "lucide-react"
import { useState } from "react"
import { Link, useNavigate } from "react-router"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
import { PageHeader } from "@/components/dossier"
import { Button } from "@/components/ui/button"
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
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { countOf, formatDay } from "@/lib/format"

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
        <Button>New process</Button>
      </DialogTrigger>
      <DialogContent className="bg-surface">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim() && !retentionInvalid) create.mutate()
          }}
          className="space-y-6"
        >
          <DialogHeader>
            <DialogTitle className="text-2xl">Open a new process file</DialogTitle>
            <DialogDescription className="text-fg-muted">
              One file per process. Every meeting about it is merged into a single map.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <label htmlFor="project-name" className="label block">
              Process name
            </label>
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
            <label htmlFor="project-retention" className="label block">
              Delete meeting content after
            </label>
            <div className="flex items-center gap-2">
              <Input
                id="project-retention"
                inputMode="numeric"
                placeholder="Keep"
                className="tabular w-28"
                value={retention}
                onChange={(e) => setRetention(e.target.value.replace(/[^\d]/g, ""))}
                aria-invalid={retentionInvalid}
                aria-describedby="retention-help"
              />
              <span className="text-sm text-fg-muted">days</span>
            </div>
            <p id="retention-help" className="text-sm text-fg-muted">
              Recordings and transcript text are deleted after this many days. Maps are kept.
            </p>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || retentionInvalid || create.isPending}>
              {create.isPending ? "Opening…" : "Open file"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** The index of processes: a table of contents, not a grid of cards. */
export function Projects() {
  const [creating, setCreating] = useState(false)
  const { data, isPending, error } = useQuery({ queryKey: ["projects"], queryFn: api.projects })

  return (
    <Page>
      <PageHeader
        title="Processes"
        revision={data ? countOf(data.length, "process", "processes") : undefined}
        actions={<NewProjectDialog open={creating} onOpenChange={setCreating} />}
      />
      {isPending ? (
        <div className="space-y-3" aria-busy>
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-16 rounded-sm bg-raised" />
          ))}
        </div>
      ) : error ? (
        <p role="alert" className="text-signal">
          Couldn't load the index: {error.message}
        </p>
      ) : data.length === 0 ? (
        <div className="measure py-10">
          <p className="macro text-[clamp(2rem,5vw,3rem)]">No processes yet</p>
          <p className="mt-2 text-fg-muted">
            Open a file for a process, then add a meeting transcript or recording. The map is drafted from what was
            said, and every step keeps a reference to the words behind it.
          </p>
          <Button className="mt-6" onClick={() => setCreating(true)}>
            Create the first process
          </Button>
        </div>
      ) : (
        <ul className="border-t-2 border-fg">
          {data.map((p, i) => {
            const needs = p.open_conflicts + p.open_policy_differences + p.open_gaps
            return (
              <li key={p.id} className="border-b-2 border-fg">
                <Link
                  to={`/projects/${p.id}`}
                  className="transition-quiet group grid grid-cols-[auto_1fr_auto] items-center gap-x-5 py-5 hover:bg-surface sm:gap-x-8 sm:px-3"
                >
                  <span
                    className="macro tabular text-[clamp(2rem,5vw,3.5rem)] text-fg-subtle group-hover:text-fg"
                    aria-hidden
                  >
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="min-w-0">
                    <span className="macro block text-[clamp(1.35rem,3vw,2rem)] break-words">{p.name}</span>
                    <span className="label tabular mt-2 block">
                      {countOf(p.transcripts.filter((t) => t.purpose === "meeting").length, "meeting")}
                      {p.revised_at ? ` · revised ${formatDay(p.revised_at)}` : " · no map yet"}
                      <span className="text-fg-subtle">
                        {" "}
                        · P-{p.id.slice(0, 4).toUpperCase()}
                        {p.map_version ? ` · REV ${p.map_version}` : ""}
                      </span>
                    </span>
                  </span>
                  <span className="flex items-center gap-4">
                    {needs > 0 ? (
                      <span className="label flex items-center gap-2 font-semibold whitespace-nowrap text-signal">
                        <span className="stripes inline-block h-3 w-6" aria-hidden />
                        {needs} need{needs === 1 ? "s" : ""} you
                      </span>
                    ) : p.merged_map_id ? (
                      <span className="label whitespace-nowrap">All settled</span>
                    ) : null}
                    <ArrowRight className="size-6 shrink-0 text-fg" strokeWidth={2.5} aria-hidden />
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Page>
  )
}
