import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
import { PageHeader, Panel } from "@/components/kit"
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
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { formatDate, formatDay } from "@/lib/format"
import type { ApiKey } from "@/lib/types"

function NewKey() {
  const qc = useQueryClient()
  const [name, setName] = useState("")
  const [created, setCreated] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const create = useMutation({
    mutationFn: () => api.createKey(name.trim()),
    onSuccess: (k) => {
      setCreated(k.key)
      setCopied(false)
      setName("")
      qc.invalidateQueries({ queryKey: ["keys"] })
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <div className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) create.mutate()
        }}
      >
        <div className="min-w-[220px] flex-1 space-y-1.5">
          <label htmlFor="key-name" className="eyebrow block">
            New key name
          </label>
          <Input
            id="key-name"
            placeholder="e.g. ci, zapier, alice-laptop"
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <Button type="submit" variant="outline" disabled={!name.trim() || create.isPending}>
          {create.isPending ? "Creating…" : "Create key"}
        </Button>
      </form>
      {created && (
        <div className="space-y-2 rounded-md border border-brand/40 bg-brand-tint p-3" role="status">
          <p className="text-sm font-bold">Copy this key now. It won't be shown again.</p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 rounded-md border border-line bg-app px-2 py-1.5 font-mono text-xs break-all">
              {created}
            </code>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                navigator.clipboard.writeText(created).then(
                  () => setCopied(true),
                  () => toast.error("Couldn't copy. Select the key and copy it manually."),
                )
              }
            >
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function RevokeButton({ k }: { k: ApiKey }) {
  const qc = useQueryClient()
  const revoke = useMutation({
    mutationFn: () => api.revokeKey(k.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["keys"] })
      toast.success(`Revoked “${k.name}”`)
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="sm" className="text-fg-muted hover:text-bad">
          Revoke
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Revoke “{k.name}”?</AlertDialogTitle>
          <AlertDialogDescription>
            Anything using this key stops working immediately.
            {k.current && " This is the key this browser is signed in with: you'll be signed out."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep it</AlertDialogCancel>
          <AlertDialogAction onClick={() => revoke.mutate()}>Revoke key</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

const ACTION_LABEL: Record<string, string> = {
  create: "Opened a process file",
  upload: "Added a meeting",
  process: "Started processing",
  merge: "Merged a meeting in",
  edit: "Edited a map",
  export: "Exported",
  delete: "Deleted a process",
  resolve_conflict: "Settled a point",
  retention_purge: "Retention: content deleted",
  create_key: "Created an API key",
  revoke_key: "Revoked an API key",
  set_speaker_role: "Tagged a speaker's role",
  dismiss_gap: "Dismissed a gap",
  request_signoff: "Asked for sign-off",
  revoke_signoff: "Withdrew a sign-off link",
  signoff: "Sign-off answered",
}

/** Readable details only: ids are noise to a reader (they stay in the API). */
function details(d: Record<string, unknown>): string {
  return Object.entries(d)
    .filter(([k, v]) => v != null && v !== "" && !k.endsWith("id"))
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${String(v)}`)
    .join(" · ")
}

const TH = "pb-2 pr-3 text-left text-xs font-medium text-fg-muted"
const TD = "py-2.5 pr-3 align-baseline"

export function Settings() {
  const keys = useQuery({ queryKey: ["keys"], queryFn: api.keys })
  const usage = useQuery({ queryKey: ["usage"], queryFn: api.usage })
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.audit(50) })

  return (
    <Page>
      <PageHeader title="Settings" meta="API keys, usage and the record of who did what." />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Panel title="API keys" id="keys" aside="Only a hash of each key is stored">
          <NewKey />
          {keys.isPending ? (
            <Skeleton className="mt-6 h-24 rounded-md bg-raised" />
          ) : (
            <table className="mt-6 w-full text-[0.95rem]">
              <caption className="sr-only">API keys</caption>
              <thead className="border-b border-line">
                <tr>
                  <th className={TH}>Name</th>
                  <th className={TH}>Key</th>
                  <th className={`${TH} hidden sm:table-cell`}>Issued</th>
                  <th className={TH}>Status</th>
                  <th className="w-20">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {keys.data?.map((k) => (
                  <tr key={k.id} className="border-b border-line">
                    <td className={`${TD} font-bold`}>{k.name}</td>
                    <td className={TD}>
                      <code className="font-mono text-xs text-fg-muted">t2b_{k.prefix}_…</code>
                    </td>
                    <td className={`${TD} tabular hidden text-sm text-fg-muted sm:table-cell`}>
                      {formatDay(k.created_at)}
                    </td>
                    <td className={`${TD} text-sm`}>
                      {k.revoked_at ? (
                        <span className="text-fg-muted">Revoked {formatDay(k.revoked_at)}</span>
                      ) : k.current ? (
                        "Active · this browser"
                      ) : (
                        "Active"
                      )}
                    </td>
                    <td className="py-1 text-right">{!k.revoked_at && <RevokeButton k={k} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel title="This month" id="usage">
          {usage.isPending ? (
            <Skeleton className="h-20 rounded-md bg-raised" />
          ) : usage.data ? (
            <dl className="space-y-5">
              <div>
                <dt className="text-sm text-fg-muted">Meetings processed</dt>
                <dd className="tabular text-3xl font-semibold">
                  {usage.data.jobs_this_month}
                  {usage.data.monthly_jobs_quota != null && (
                    <span className="text-lg font-normal text-fg-muted"> of {usage.data.monthly_jobs_quota}</span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-sm text-fg-muted">Rate limits, per key</dt>
                <dd className="tabular text-sm">
                  {usage.data.rate_limit_per_minute} requests a minute; {usage.data.rate_limit_heavy_per_minute} for
                  uploads, processing, chat edits and image exports
                </dd>
              </div>
            </dl>
          ) : null}
        </Panel>

        <Panel
          title="Activity"
          id="activity"
          className="lg:col-span-2"
          aside="By API key · meeting content is never recorded here"
        >
          {audit.isPending ? (
            <Skeleton className="h-32 rounded-md bg-raised" />
          ) : (
            <table className="w-full text-[0.95rem]">
              <caption className="sr-only">Recent activity</caption>
              <thead className="border-b border-line">
                <tr>
                  <th className={TH}>When</th>
                  <th className={TH}>What</th>
                  <th className={`${TH} hidden md:table-cell`}>Details</th>
                  <th className={`${TH} hidden sm:table-cell`}>By</th>
                </tr>
              </thead>
              <tbody>
                {audit.data?.map((a, i) => {
                  const key = keys.data?.find((k) => k.id === a.api_key_id)
                  const d = details(a.details)
                  return (
                    <tr key={i} className="border-b border-line">
                      <td className={`${TD} tabular text-sm whitespace-nowrap text-fg-muted`}>
                        {formatDate(a.created_at)}
                      </td>
                      <td className={TD}>{ACTION_LABEL[a.action] ?? a.action}</td>
                      <td className={`${TD} hidden max-w-md truncate text-sm text-fg-muted md:table-cell`} title={d}>
                        {d}
                      </td>
                      <td className={`${TD} hidden text-sm text-fg-muted sm:table-cell`}>
                        {key ? key.name : a.api_key_id ? "another key" : "the system"}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </Page>
  )
}
