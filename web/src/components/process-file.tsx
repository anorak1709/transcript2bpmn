import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, CircleDashed, Clock, PenLine, X } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

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
import { api } from "@/lib/api"
import { formatDay, ROLE_LABEL } from "@/lib/format"
import type { Project, Signoff, SignoffStatus, SpeakerRole } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Drop area for files. Meetings and policy documents share it; only what's accepted differs. */
export function AddFiles({
  project,
  purpose,
  accept,
  prompt,
  hint,
}: {
  project: Project
  purpose: "meeting" | "policy"
  accept: string
  prompt: string
  hint: string
}) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState<string | null>(null)
  const id = `upload-${purpose}`

  async function handle(files: FileList | null) {
    if (!files?.length) return
    for (const file of Array.from(files)) {
      setUploading(file.name)
      try {
        const t = await api.upload(project.id, file, purpose)
        await api.process(t.id) // upload and process in one step: that's what people want
        toast.success(`${file.name} uploaded`, {
          description: purpose === "policy" ? "It's being compared with the map." : "Processing has started.",
        })
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
        dragging ? "border-fg bg-raised" : "border-line-strong",
      )}
    >
      <div>
        <p className="text-[1.05rem]">{prompt}</p>
        <p className="text-xs text-fg-muted">{hint}</p>
      </div>
      <input
        ref={input}
        id={id}
        type="file"
        multiple
        accept={accept}
        className="sr-only"
        onChange={(e) => void handle(e.target.files)}
      />
      <Button asChild variant="outline" size="sm" disabled={!!uploading}>
        <label htmlFor={id} className="cursor-pointer">
          {uploading ? `Uploading ${uploading}…` : "Choose files"}
        </label>
      </Button>
    </div>
  )
}

/** Speakers heard in the meetings, each tagged once with their role. Roles show next to their
 *  quotes in every disagreement. */
export function Speakers({ projectId, refresh }: { projectId: string; refresh: unknown }) {
  const qc = useQueryClient()
  const speakers = useQuery({ queryKey: ["speakers", projectId, refresh], queryFn: () => api.speakers(projectId) })
  const set = useMutation({
    mutationFn: ({ name, role }: { name: string; role: SpeakerRole | null }) =>
      api.setSpeakerRole(projectId, name, role),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["speakers", projectId] })
      qc.invalidateQueries({ queryKey: ["conflicts", projectId] })
    },
    onError: (e) => toast.error(e.message),
  })
  if (!speakers.data?.length) {
    return <p className="py-2 text-sm text-fg-muted">Speakers appear here once a meeting is processed.</p>
  }
  return (
    <table className="w-full text-[0.95rem]">
      <caption className="sr-only">Speakers and their roles</caption>
      <thead className="sr-only">
        <tr>
          <th>Speaker</th>
          <th>Role</th>
        </tr>
      </thead>
      <tbody>
        {speakers.data.map((s) => (
          <tr key={s.name} className="border-b border-line">
            <td className="py-2 pr-3">
              <span className="font-bold">{s.name}</span>
              <span className="tabular block text-xs text-fg-muted">
                {s.lines} line{s.lines === 1 ? "" : "s"} · {s.meetings} meeting{s.meetings === 1 ? "" : "s"}
              </span>
            </td>
            <td className="py-2 text-right">
              <label className="sr-only" htmlFor={`role-${s.name}`}>
                Role of {s.name}
              </label>
              <select
                id={`role-${s.name}`}
                value={s.role ?? ""}
                disabled={set.isPending}
                onChange={(e) => set.mutate({ name: s.name, role: (e.target.value || null) as SpeakerRole | null })}
                className="h-8 rounded-sm border border-control bg-surface px-2 text-sm text-fg"
              >
                <option value="">Role not set</option>
                {(Object.keys(ROLE_LABEL) as SpeakerRole[]).map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABEL[r][0].toUpperCase() + ROLE_LABEL[r].slice(1)}
                  </option>
                ))}
              </select>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const SIGNOFF_MARK: Record<SignoffStatus, { icon: typeof Check; text: string }> = {
  pending: { icon: Clock, text: "Awaiting review" },
  approved: { icon: Check, text: "Approved" },
  changes_requested: { icon: PenLine, text: "Changes requested" },
  revoked: { icon: X, text: "Withdrawn" },
  expired: { icon: CircleDashed, text: "Link expired" },
}

function RequestSignoff({ project }: { project: Project }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [lanes, setLanes] = useState<string[]>([])
  const [link, setLink] = useState<string | null>(null)
  const map = useQuery({
    queryKey: ["map", project.merged_map_id],
    queryFn: () => api.map(project.merged_map_id!),
    enabled: open && !!project.merged_map_id,
  })
  const create = useMutation({
    mutationFn: () => api.requestSignoff(project.id, name.trim(), lanes),
    onSuccess: (s) => {
      setLink(`${window.location.origin}/app/review/${s.token}`)
      qc.invalidateQueries({ queryKey: ["signoffs", project.id] })
    },
    onError: (e) => toast.error(e.message),
  })
  const reset = (v: boolean) => {
    setOpen(v)
    if (!v) {
      setName("")
      setLanes([])
      setLink(null)
    }
  }
  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" disabled={!project.merged_map_id}>
          Ask someone to sign off…
        </Button>
      </DialogTrigger>
      <DialogContent className="bg-surface">
        {link ? (
          <div className="space-y-4">
            <DialogHeader>
              <DialogTitle className="text-2xl">Send this link to {name}</DialogTitle>
              <DialogDescription className="text-fg-muted">
                It shows only their part of the map and needs no account. Copy it now: it isn't shown again. It works
                for 30 days, and you can withdraw it at any time.
              </DialogDescription>
            </DialogHeader>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 rounded-sm border border-line bg-bg px-2 py-1.5 font-mono text-xs break-all">
                {link}
              </code>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  navigator.clipboard.writeText(link).then(
                    () => toast.success("Link copied"),
                    () => toast.error("Couldn't copy. Select the link and copy it manually."),
                  )
                }
              >
                Copy
              </Button>
            </div>
            <DialogFooter>
              <Button onClick={() => reset(false)}>Done</Button>
            </DialogFooter>
          </div>
        ) : (
          <form
            className="space-y-5"
            onSubmit={(e) => {
              e.preventDefault()
              if (name.trim() && lanes.length) create.mutate()
            }}
          >
            <DialogHeader>
              <DialogTitle className="text-2xl">Ask for sign-off</DialogTitle>
              <DialogDescription className="text-fg-muted">
                They review only the steps in the lanes you choose, and approve or ask for changes. Their answer is
                recorded with the map version they saw.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-1.5">
              <label htmlFor="signoff-name" className="label block">
                Who
              </label>
              <Input
                id="signoff-name"
                value={name}
                maxLength={255}
                placeholder="e.g. Sana, Treasury lead"
                onChange={(e) => setName(e.target.value)}
                autoFocus
              />
            </div>
            <fieldset className="space-y-1.5">
              <legend className="label">Their part of the map</legend>
              {map.data ? (
                map.data.model.lanes.map((l) => (
                  <label key={l.id} className="flex items-center gap-2 text-[0.95rem]">
                    <input
                      type="checkbox"
                      className="size-4 accent-[var(--fg)]"
                      checked={lanes.includes(l.id)}
                      onChange={(e) => setLanes(e.target.checked ? [...lanes, l.id] : lanes.filter((x) => x !== l.id))}
                    />
                    {l.name}
                  </label>
                ))
              ) : (
                <p className="text-sm text-fg-muted">Loading lanes…</p>
              )}
            </fieldset>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => reset(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!name.trim() || !lanes.length || create.isPending}>
                {create.isPending ? "Creating…" : "Create review link"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** Who has been asked to confirm their part, and what they said. */
export function Signoffs({ project }: { project: Project }) {
  const qc = useQueryClient()
  const rows = useQuery({ queryKey: ["signoffs", project.id], queryFn: () => api.signoffs(project.id) })
  const revoke = useMutation({
    mutationFn: (id: string) => api.revokeSignoff(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["signoffs", project.id] }),
    onError: (e) => toast.error(e.message),
  })
  const list: Signoff[] = rows.data ?? []
  return (
    <div className="space-y-4">
      {list.length ? (
        <table className="w-full text-[0.95rem]">
          <caption className="sr-only">Sign-off requests</caption>
          <thead className="border-b border-line">
            <tr>
              <th className="label py-2 pr-3 text-left font-sans">Who</th>
              <th className="label hidden py-2 pr-3 text-left font-sans sm:table-cell">Their part</th>
              <th className="label py-2 pr-3 text-left font-sans">Status</th>
              <th className="w-24">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {list.map((s) => {
              const { icon: Icon, text } = SIGNOFF_MARK[s.status]
              const stale =
                s.decided_version != null && s.current_version != null && s.current_version > s.decided_version
              return (
                <tr key={s.id} className="border-b border-line align-baseline">
                  <td className="py-2.5 pr-3 font-bold">{s.name}</td>
                  <td className="hidden py-2.5 pr-3 text-sm text-fg-muted sm:table-cell">{s.lanes.join(", ")}</td>
                  <td className="py-2.5 pr-3 text-sm">
                    <span className="inline-flex items-center gap-1.5">
                      <Icon className="size-3.5" aria-hidden /> {text}
                      {s.decided_at && (
                        <span className="text-fg-muted">
                          {" "}
                          · {formatDay(s.decided_at)}, v{s.decided_version}
                        </span>
                      )}
                    </span>
                    {stale && (
                      <span className="block text-xs text-signal">
                        The map has changed since (now v{s.current_version}).
                      </span>
                    )}
                    {s.comment && <span className="mt-0.5 block text-[0.98rem]">“{s.comment}”</span>}
                  </td>
                  <td className="py-1 text-right">
                    {(s.status === "pending" || s.status === "approved" || s.status === "changes_requested") && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-fg-muted hover:text-signal"
                        disabled={revoke.isPending}
                        onClick={() => revoke.mutate(s.id)}
                      >
                        Withdraw link
                      </Button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : (
        <p className="text-sm text-fg-muted">
          Nobody has been asked yet. Send each person a private link to confirm just their part of the map.
        </p>
      )}
      <RequestSignoff project={project} />
    </div>
  )
}
