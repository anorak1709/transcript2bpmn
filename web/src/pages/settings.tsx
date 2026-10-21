import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
import { PageHeader, Section } from "@/components/dossier"
import { ImproveDrafts, Team } from "@/components/workspace-settings"
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
          <label htmlFor="key-name" className="label block">
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
        <div className="space-y-2 border-l-2 border-ink bg-sheet py-3 pr-3 pl-4" role="status">
          <p className="text-sm font-bold">Copy this key now. It won't be shown again.</p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 rounded-sm border border-hairline bg-paper px-2 py-1.5 font-mono text-xs break-all">
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
        <Button variant="ghost" size="sm" className="text-graphite hover:text-oxblood">
          Revoke
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent className="bg-sheet">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-2xl">Revoke “{k.name}”?</AlertDialogTitle>
          <AlertDialogDescription className="text-graphite">
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
  sign_in: "Signed in",
  invite: "Invited a colleague",
  cancel_invite: "Cancelled an invitation",
  share_corrections: "Changed correction sharing",
  review_step: "Checked a step",
  ai_improvements: "Asked AI for improvements",
  live_start: "Started a live interview",
  live_finish: "Finished a live interview",
}

/** Readable details only: ids are noise to a reader (they stay in the API). */
function details(d: Record<string, unknown>): string {
  return Object.entries(d)
    .filter(([k, v]) => v != null && v !== "" && !k.endsWith("id"))
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${String(v)}`)
    .join(" · ")
}

const TH = "label py-2 pr-3 text-left font-sans"
const TD = "py-2.5 pr-3 align-baseline"

export function Settings() {
  const keys = useQuery({ queryKey: ["keys"], queryFn: api.keys })
  const usage = useQuery({ queryKey: ["usage"], queryFn: api.usage })
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.audit(50) })

  return (
    <Page>
      <PageHeader eyebrow="Workspace" title="Settings" revision="API keys, usage and the record of who did what." />

      <div className="grid gap-x-14 gap-y-14 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Section title="API keys" id="keys" aside="Only a hash of each key is stored">
          <NewKey />
          {keys.isPending ? (
            <Skeleton className="mt-6 h-24 rounded-sm bg-paper-shade" />
          ) : (
            <table className="mt-6 w-full text-[0.95rem]">
              <caption className="sr-only">API keys</caption>
              <thead className="border-b border-hairline">
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
                  <tr key={k.id} className="border-b border-hairline">
                    <td className={`${TD} font-bold`}>{k.name}</td>
                    <td className={TD}>
                      <code className="font-mono text-xs text-graphite">t2b_{k.prefix}_…</code>
                    </td>
                    <td className={`${TD} tabular hidden text-sm text-graphite sm:table-cell`}>
                      {formatDay(k.created_at)}
                    </td>
                    <td className={`${TD} text-sm`}>
                      {k.revoked_at ? (
                        <span className="text-graphite">Revoked {formatDay(k.revoked_at)}</span>
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
        </Section>

        <Team />
        <ImproveDrafts />

        <Section title="This month" id="usage">
          {usage.isPending ? (
            <Skeleton className="h-20 rounded-sm bg-paper-shade" />
          ) : usage.data ? (
            <dl className="space-y-5">
              <div>
                <dt className="text-sm text-graphite">Meetings processed</dt>
                <dd className="serif tabular text-[2.5rem] leading-none">
                  {usage.data.jobs_this_month}
                  {usage.data.monthly_jobs_quota != null && (
                    <span className="text-2xl text-graphite"> of {usage.data.monthly_jobs_quota}</span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-sm text-graphite">Rate limits, per key</dt>
                <dd className="tabular text-sm">
                  {usage.data.rate_limit_per_minute} requests a minute; {usage.data.rate_limit_heavy_per_minute} for
                  uploads, processing, chat edits and image exports
                </dd>
              </div>
            </dl>
          ) : null}
        </Section>

        <Section
          title="Activity"
          id="activity"
          className="lg:col-span-2"
          aside="By API key · meeting content is never recorded here"
        >
          {audit.isPending ? (
            <Skeleton className="h-32 rounded-sm bg-paper-shade" />
          ) : (
            <table className="w-full text-[0.95rem]">
              <caption className="sr-only">Recent activity</caption>
              <thead className="border-b border-hairline">
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
                    <tr key={i} className="border-b border-hairline">
                      <td className={`${TD} tabular text-sm whitespace-nowrap text-graphite`}>
                        {formatDate(a.created_at)}
                      </td>
                      <td className={TD}>{ACTION_LABEL[a.action] ?? a.action}</td>
                      <td className={`${TD} hidden max-w-md truncate text-sm text-graphite md:table-cell`} title={d}>
                        {d}
                      </td>
                      <td className={`${TD} hidden text-sm text-graphite sm:table-cell`}>
                        {key ? key.name : a.api_key_id ? "another key" : "the system"}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </Section>
      </div>
    </Page>
  )
}
