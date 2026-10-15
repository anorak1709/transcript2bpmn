import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Copy, KeyRound, Loader2, Plus } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
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
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api } from "@/lib/api"
import { formatDate } from "@/lib/format"
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
        <div className="min-w-[220px] flex-1 space-y-2">
          <Label htmlFor="key-name">New key name</Label>
          <Input
            id="key-name"
            placeholder="e.g. ci, zapier, alice-laptop"
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />} Create key
        </Button>
      </form>
      {created && (
        <div className="space-y-2 rounded-lg border border-primary/40 bg-muted/50 p-3" role="status">
          <p className="text-sm font-medium">Copy this key now. It won't be shown again.</p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 break-all rounded bg-background px-2 py-1.5 text-xs">{created}</code>
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
              {copied ? <Check aria-hidden /> : <Copy aria-hidden />} {copied ? "Copied" : "Copy"}
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
      toast.success(`Revoked "${k.name}"`)
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive">
          Revoke
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Revoke "{k.name}"?</AlertDialogTitle>
          <AlertDialogDescription>
            Anything using this key stops working immediately.
            {k.current && " This is the key this browser is signed in with: you'll be signed out."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-white hover:bg-destructive/90"
            onClick={() => revoke.mutate()}
          >
            Revoke key
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

const ACTION_LABEL: Record<string, string> = {
  create: "Created project",
  upload: "Uploaded",
  process: "Started processing",
  merge: "Merged a meeting",
  edit: "Edited map",
  export: "Exported",
  delete: "Deleted project",
  resolve_conflict: "Resolved conflict",
  retention_purge: "Retention purge",
  create_key: "Created API key",
  revoke_key: "Revoked API key",
}

export function Settings() {
  const keys = useQuery({ queryKey: ["keys"], queryFn: api.keys })
  const usage = useQuery({ queryKey: ["usage"], queryFn: api.usage })
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.audit(50) })

  return (
    <Page title="Settings" description="API keys, usage and activity for your workspace.">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader>
            <CardTitle asChild className="flex items-center gap-2 text-base">
              <h2>
                <KeyRound className="size-4" aria-hidden /> API keys
              </h2>
            </CardTitle>
            <CardDescription>Keys belong to your workspace. Only a hash of each key is stored.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <NewKey />
            {keys.isPending ? (
              <Skeleton className="h-24" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Key</TableHead>
                    <TableHead className="hidden sm:table-cell">Created</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="w-24">
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {keys.data?.map((k) => (
                    <TableRow key={k.id}>
                      <TableCell className="font-medium">{k.name}</TableCell>
                      <TableCell>
                        <code className="text-xs">t2b_{k.prefix}_…</code>
                      </TableCell>
                      <TableCell className="hidden text-muted-foreground sm:table-cell">
                        {formatDate(k.created_at)}
                      </TableCell>
                      <TableCell>
                        {k.revoked_at ? (
                          <Badge variant="outline">Revoked</Badge>
                        ) : k.current ? (
                          <Badge>This browser</Badge>
                        ) : (
                          <Badge variant="secondary">Active</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">{!k.revoked_at && <RevokeButton k={k} />}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle asChild className="text-base">
              <h2>This month</h2>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {usage.isPending ? (
              <Skeleton className="h-20" />
            ) : usage.data ? (
              <dl className="space-y-3 text-sm">
                <div>
                  <dt className="text-muted-foreground">Meetings processed</dt>
                  <dd className="text-2xl font-semibold tabular-nums">
                    {usage.data.jobs_this_month}
                    {usage.data.monthly_jobs_quota != null && (
                      <span className="text-base font-normal text-muted-foreground">
                        {" "}
                        / {usage.data.monthly_jobs_quota}
                      </span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Rate limits per key</dt>
                  <dd>
                    {usage.data.rate_limit_per_minute}/min, {usage.data.rate_limit_heavy_per_minute}/min for uploads,
                    processing, chat and image exports
                  </dd>
                </div>
              </dl>
            ) : null}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle asChild className="text-base">
              <h2>Recent activity</h2>
            </CardTitle>
            <CardDescription>Who did what, by API key. Meeting content is never logged here.</CardDescription>
          </CardHeader>
          <CardContent>
            {audit.isPending ? (
              <Skeleton className="h-32" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead className="hidden md:table-cell">Details</TableHead>
                    <TableHead className="hidden sm:table-cell">Key</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {audit.data?.map((a, i) => {
                    const key = keys.data?.find((k) => k.id === a.api_key_id)
                    const details = Object.entries(a.details)
                      .filter(([, v]) => v != null && v !== "")
                      .map(([k, v]) => `${k.replace(/_/g, " ")}: ${String(v)}`)
                      .join(" · ")
                    return (
                      <TableRow key={i}>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {formatDate(a.created_at)}
                        </TableCell>
                        <TableCell>{ACTION_LABEL[a.action] ?? a.action}</TableCell>
                        <TableCell
                          className="hidden max-w-md truncate text-muted-foreground md:table-cell"
                          title={details}
                        >
                          {details}
                        </TableCell>
                        <TableCell className="hidden text-muted-foreground sm:table-cell">
                          {key ? key.name : a.api_key_id ? "(another key)" : "system"}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
