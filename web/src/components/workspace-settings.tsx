import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { Section } from "@/components/dossier"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import { formatDay } from "@/lib/format"
import type { Workspace } from "@/lib/types"

/** Who is in this workspace, and inviting colleagues by email. */
export function Team() {
  const qc = useQueryClient()
  const [email, setEmail] = useState("")
  const members = useQuery({ queryKey: ["members"], queryFn: api.members })
  const invites = useQuery({ queryKey: ["invites"], queryFn: api.invites })
  const me = useQuery({ queryKey: ["me"], queryFn: api.me })
  const invite = useMutation({
    mutationFn: () => api.invite(email.trim()),
    onSuccess: () => {
      toast.success(`Invitation sent to ${email.trim()}`)
      setEmail("")
      qc.invalidateQueries({ queryKey: ["invites"] })
    },
    onError: (e) => toast.error(e.message),
  })
  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelInvite(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invites"] }),
  })
  if (me.data?.sandbox) return null
  return (
    <Section title="Team" id="team" aside="Everyone here sees every process">
      <ul className="divide-y divide-line text-[0.95rem]">
        {(members.data ?? []).map((m) => (
          <li key={m.email} className="flex items-baseline justify-between gap-3 py-2">
            <span>{m.email}</span>
            <span className="text-sm text-fg-muted">{m.role === "owner" ? "Owner" : "Member"}</span>
          </li>
        ))}
        {(invites.data ?? []).map((i) => (
          <li key={i.id} className="flex items-baseline justify-between gap-3 py-2">
            <span className="text-fg-muted">{i.email}</span>
            <span className="text-sm text-fg-muted">
              Invited {formatDay(i.created_at)} ·{" "}
              <button type="button" className="underline hover:text-signal" onClick={() => cancel.mutate(i.id)}>
                Cancel
              </button>
            </span>
          </li>
        ))}
        {members.data?.length === 0 && (
          <li className="py-2 text-sm text-fg-muted">This workspace is used with API keys only.</li>
        )}
      </ul>
      <form
        className="mt-4 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (email.trim()) invite.mutate()
        }}
      >
        <div className="min-w-[220px] flex-1 space-y-1.5">
          <label htmlFor="invite-email" className="label block">
            Invite a colleague
          </label>
          <Input
            id="invite-email"
            type="email"
            placeholder="colleague@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <Button type="submit" variant="outline" disabled={!email.trim() || invite.isPending}>
          {invite.isPending ? "Sending…" : "Send invitation"}
        </Button>
      </form>
    </Section>
  )
}

const SHARING: { value: Workspace["share_corrections"]; label: string; detail: string }[] = [
  { value: "off", label: "Don't share", detail: "Corrections stay in this workspace." },
  {
    value: "anonymised",
    label: "Share what was changed",
    detail: "Which steps were renamed, moved or deleted, without meeting text or names.",
  },
  {
    value: "full",
    label: "Share with the meetings",
    detail: "Also the meeting text, so each fix can be re-run as a test of the drafting.",
  },
]

/** The corrections flywheel: every fix people make is a lesson for the drafting; sharing is opt-in. */
export function ImproveDrafts() {
  const qc = useQueryClient()
  const ws = useQuery({ queryKey: ["workspace"], queryFn: api.workspace })
  const corrections = useQuery({ queryKey: ["corrections"], queryFn: api.corrections })
  const evidence = useQuery({ queryKey: ["element-evidence"], queryFn: api.elementEvidence })
  const set = useMutation({
    mutationFn: (v: Workspace["share_corrections"]) => api.setSharing(v),
    onSuccess: (w) => qc.setQueryData(["workspace"], w),
    onError: (e) => toast.error(e.message),
  })
  const c = corrections.data
  const ev = evidence.data
  return (
    <Section title="Help improve the drafts" id="improve" aside="Opt-in, per workspace">
      <p className="measure text-[0.95rem] text-fg-muted">
        {c?.total
          ? `People here have corrected the AI's drafts ${c.total} time${c.total === 1 ? "" : "s"} (${Object.entries(
              c.by_kind,
            )
              .map(([k, n]) => `${n} ${k}`)
              .join(", ")}).`
          : "No corrections yet."}{" "}
        Each rename, move or delete shows where the drafting was wrong. Sharing them turns them into test cases.
      </p>
      <fieldset className="mt-4 space-y-2" disabled={!ws.data || set.isPending}>
        <legend className="sr-only">Share corrections</legend>
        {SHARING.map((o) => (
          <label key={o.value} className="flex items-start gap-2.5 text-[0.95rem]">
            <input
              type="radio"
              name="share-corrections"
              className="mt-1 accent-[var(--fg)]"
              checked={ws.data?.share_corrections === o.value}
              onChange={() => set.mutate(o.value)}
            />
            <span>
              {o.label}
              <span className="block text-sm text-fg-muted">{o.detail}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {ev && ev.meetings > 0 && (
        <p className="mt-6 text-sm text-fg-muted">
          Of {ev.meetings} meeting{ev.meetings === 1 ? "" : "s"} here, {ev.with_timers} describe waits or deadlines and{" "}
          {ev.with_subprocesses} describe separate sub-processes: the evidence for adding timer and sub-process steps to
          the drafts.
        </p>
      )}
    </Section>
  )
}
