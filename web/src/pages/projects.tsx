import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
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
import { countOf, formatDay, roman } from "@/lib/format"

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
      <DialogContent className="bg-sheet">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim() && !retentionInvalid) create.mutate()
          }}
          className="space-y-6"
        >
          <DialogHeader>
            <DialogTitle className="text-2xl">Open a new process file</DialogTitle>
            <DialogDescription className="text-graphite">
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
              <span className="text-sm text-graphite">days</span>
            </div>
            <p id="retention-help" className="text-sm text-graphite">
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
        eyebrow="Index"
        title="Processes"
        revision={data ? `${countOf(data.length, "process", "processes")} on file` : undefined}
        actions={<NewProjectDialog open={creating} onOpenChange={setCreating} />}
      />
      {isPending ? (
        <div className="space-y-3" aria-busy>
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-16 rounded-sm bg-paper-shade" />
          ))}
        </div>
      ) : error ? (
        <p role="alert" className="text-oxblood">
          Couldn't load the index: {error.message}
        </p>
      ) : data.length === 0 ? (
        <div className="measure py-10">
          <p className="text-2xl">Nothing on file yet.</p>
          <p className="mt-2 text-graphite">
            Open a file for a process, then add a meeting transcript or recording. The map is drafted from what was
            said, and every step keeps a reference to the words behind it.
          </p>
          <Button className="mt-6" onClick={() => setCreating(true)}>
            Open the first file
          </Button>
        </div>
      ) : (
        <ol className="border-t border-hairline">
          {data.map((p, i) => (
            <li key={p.id} className="border-b border-hairline">
              <Link
                to={`/projects/${p.id}`}
                className="transition-quiet group grid grid-cols-[2.5rem_1fr_auto] items-baseline gap-x-4 px-2 py-5 hover:bg-paper-shade"
              >
                <span className="tabular text-lg text-graphite" aria-hidden>
                  {roman(i + 1)}.
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[1.6rem] leading-tight group-hover:underline group-hover:decoration-1 group-hover:underline-offset-4">
                    {p.name}
                  </span>
                  <span className="tabular mt-1 block text-sm text-graphite">
                    {countOf(p.transcripts.filter((t) => t.purpose === "meeting").length, "meeting")}
                    {p.revised_at ? ` · revised ${formatDay(p.revised_at)}` : " · no map yet"}
                    {p.map_version ? ` · v${p.map_version}` : ""}
                    {p.retention_days ? ` · content kept ${p.retention_days} days` : ""}
                  </span>
                </span>
                <span className="text-right text-sm whitespace-nowrap">
                  {p.open_conflicts > 0 ? (
                    <span className="text-oxblood">{countOf(p.open_conflicts, "point").toLowerCase()} to settle</span>
                  ) : p.merged_map_id ? (
                    <span className="text-graphite">Settled</span>
                  ) : null}
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </Page>
  )
}
