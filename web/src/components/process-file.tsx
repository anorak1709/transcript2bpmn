import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, CircleDashed, Clock, Copy, PenLine, Upload, X } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { Chip, Empty, ItemId } from "@/components/kit"
import { ITEM, type Tone } from "@/lib/items"
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
import type { Gap, Project, Signoff, SignoffStatus, SpeakerRole } from "@/lib/types"
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
    qc.invalidateQueries({ queryKey: ["projects"] })
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
        "transition-quiet flex flex-wrap items-center gap-3 rounded-lg border border-dashed px-4 py-4",
        dragging ? "border-brand bg-brand-tint" : "border-line-strong",
      )}
    >
      <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-md bg-raised text-fg-muted">
        <Upload className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{prompt}</p>
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

/** Speakers heard in the meetings, each tagged once with their role. */
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
    return <Empty title="No speakers yet">They appear here once a meeting is processed.</Empty>
  }
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Speakers and their roles</caption>
      <thead>
        <tr className="border-b border-line text-left text-xs text-fg-muted">
          <th className="pb-2 font-medium">Speaker</th>
          <th className="hidden pb-2 font-medium sm:table-cell">Heard in</th>
          <th className="pb-2 text-right font-medium">Role</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {speakers.data.map((s) => (
          <tr key={s.name}>
            <td className="py-2.5 font-medium">{s.name}</td>
            <td className="tabular hidden py-2.5 text-fg-muted sm:table-cell">
              {s.lines} line{s.lines === 1 ? "" : "s"} · {s.meetings} meeting{s.meetings === 1 ? "" : "s"}
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
                className="h-8 rounded-md border border-control bg-app px-2 text-sm text-fg"
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

const GAP_LABEL: Record<Gap["kind"], string> = {
  one_outcome: "Only one outcome",
  no_owner: "No owner",
  dead_end: "Leads nowhere",
  no_trigger: "Nothing leads here",
  no_exception: "No rejection path",
}

/** What nobody said (G1…). */
export function Gaps({ gaps, projectId }: { gaps: Gap[]; projectId: string }) {
  const qc = useQueryClient()
  const dismiss = useMutation({
    mutationFn: (id: string) => api.dismissGap(projectId, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["gaps", projectId] })
      qc.invalidateQueries({ queryKey: ["inbox"] })
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <div className="space-y-3">
      {gaps.map((g, i) => (
        <article
          key={g.id}
          id={`G${i + 1}`}
          className="scroll-mt-24 rounded-lg border border-line bg-panel p-4 target:border-brand/60"
        >
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex items-center gap-2">
                <ItemId id={`G${i + 1}`} tone={ITEM.gap.tone} />
                <span className="text-xs font-medium text-fg-muted">{GAP_LABEL[g.kind]}</span>
              </div>
              <p className="text-[0.95rem] leading-relaxed">{g.description}</p>
              <p className="text-sm text-fg-muted">
                <span className="font-medium text-fg-muted">Ask: </span>
                {g.question}
              </p>
            </div>
            <Button size="sm" variant="ghost" disabled={dismiss.isPending} onClick={() => dismiss.mutate(g.id)}>
              Not a gap
            </Button>
          </div>
        </article>
      ))}
    </div>
  )
}

const SIGNOFF_MARK: Record<SignoffStatus, { icon: typeof Check; text: string; tone: Tone }> = {
  pending: { icon: Clock, text: "Awaiting review", tone: "info" },
  approved: { icon: Check, text: "Approved", tone: "ok" },
  changes_requested: { icon: PenLine, text: "Changes requested", tone: "warn" },
  revoked: { icon: X, text: "Withdrawn", tone: "neutral" },
  expired: { icon: CircleDashed, text: "Link expired", tone: "neutral" },
}

export function RequestSignoff({ project }: { project: Project }) {
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
        <Button disabled={!project.merged_map_id}>Ask for sign-off</Button>
      </DialogTrigger>
      <DialogContent>
        {link ? (
          <div className="space-y-4">
            <DialogHeader>
              <DialogTitle>Send this link to {name}</DialogTitle>
              <DialogDescription>
                It shows only their part of the map and needs no account. Copy it now: it isn't shown again. It works
                for 30 days, and you can withdraw it at any time.
              </DialogDescription>
            </DialogHeader>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 rounded-md border border-line bg-app px-2.5 py-2 font-mono text-xs break-all">
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
                <Copy aria-hidden /> Copy
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
              <DialogTitle>Ask for sign-off</DialogTitle>
              <DialogDescription>
                They review only the steps in the lanes you choose, then approve or ask for changes. Their answer is
                recorded with the map version they saw.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-1.5">
              <label htmlFor="signoff-name" className="eyebrow block">
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
            <fieldset className="space-y-1">
              <legend className="eyebrow mb-1.5">Their part of the map</legend>
              {map.data ? (
                map.data.model.lanes.map((l) => (
                  <label
                    key={l.id}
                    className="transition-quiet flex h-9 items-center gap-2.5 rounded-md px-2 text-sm hover:bg-raised"
                  >
                    <input
                      type="checkbox"
                      className="size-4 accent-[var(--brand)]"
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
  if (!list.length) {
    return (
      <Empty title="Nobody has been asked yet">
        Send each person a private link to confirm just their part of the map.
      </Empty>
    )
  }
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Sign-off requests</caption>
      <thead>
        <tr className="border-b border-line text-left text-xs text-fg-muted">
          <th className="pb-2 font-medium">Who</th>
          <th className="hidden pb-2 font-medium sm:table-cell">Their part</th>
          <th className="pb-2 font-medium">Status</th>
          <th className="w-32 pb-2">
            <span className="sr-only">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {list.map((s) => {
          const mark = SIGNOFF_MARK[s.status]
          const stale = s.decided_version != null && s.current_version != null && s.current_version > s.decided_version
          return (
            <tr key={s.id} className="align-top">
              <td className="py-3 font-medium">{s.name}</td>
              <td className="hidden py-3 text-fg-muted sm:table-cell">{s.lanes.join(", ")}</td>
              <td className="py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Chip tone={mark.tone} icon={mark.icon}>
                    {mark.text}
                  </Chip>
                  {s.decided_at && (
                    <span className="tabular text-xs text-fg-subtle">
                      {formatDay(s.decided_at)} · v{s.decided_version}
                    </span>
                  )}
                </div>
                {stale && (
                  <p className="mt-1 text-xs text-warn">The map has changed since (now v{s.current_version}).</p>
                )}
                {s.comment && <p className="mt-1.5 text-sm text-fg">“{s.comment}”</p>}
              </td>
              <td className="py-2 text-right">
                {["pending", "approved", "changes_requested"].includes(s.status) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="hover:text-bad"
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
  )
}
