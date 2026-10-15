import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  ArrowLeft,
  History,
  Loader2,
  Maximize,
  MessageSquare,
  Quote,
  Save,
  SendHorizontal,
  Undo2,
  UserPen,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useBlocker, useParams } from "react-router"
import { toast } from "sonner"

import { BpmnCanvas, type BpmnCanvasHandle } from "@/components/bpmn-canvas"
import { ConflictCard } from "@/components/conflict-card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api } from "@/lib/api"
import { formatDate, formatTimestamp } from "@/lib/format"
import type { ProcessMap, ProcessNode } from "@/lib/types"
import { ExportMenu } from "@/pages/project"

/** Our exports use `Node_<id>`; elements created in the editor keep their bpmn-js id. */
function modelNodeId(map: ProcessMap, xmlId: string): string | null {
  const ids = new Set(map.model.nodes.map((n) => n.id))
  const stripped = xmlId.replace(/^Node_/, "")
  return ids.has(stripped) ? stripped : ids.has(xmlId) ? xmlId : null
}

const NODE_TYPE_LABEL: Record<ProcessNode["type"], string> = {
  start_event: "Start",
  end_event: "End",
  user_task: "Task (person)",
  service_task: "Task (system)",
  exclusive_gateway: "Decision",
  parallel_gateway: "Parallel split / join",
}

function SelectedStep({ map, xmlId }: { map: ProcessMap; xmlId: string | null }) {
  if (!xmlId) return <p className="text-sm text-muted-foreground">Select a step to see where it came from.</p>
  const nodeId = modelNodeId(map, xmlId)
  const node = map.model.nodes.find((n) => n.id === nodeId)
  if (!node) return <p className="text-sm text-muted-foreground">Not saved yet. Save to keep this element.</p>
  const lane = map.model.lanes.find((l) => l.id === node.lane_id)
  const segments = new Map(map.segments.map((s) => [s.segment_id, s]))
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <h3 className="font-semibold leading-snug">{node.name || "(unnamed)"}</h3>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{NODE_TYPE_LABEL[node.type]}</span>
          <span aria-hidden>·</span>
          <span>{lane?.name ?? node.lane_id}</span>
          {node.user_added ? (
            <Badge variant="secondary">
              <UserPen aria-hidden /> Added by you
            </Badge>
          ) : node.confidence < 0.6 ? (
            <Badge variant="outline">Low confidence {Math.round(node.confidence * 100)}%</Badge>
          ) : null}
        </div>
      </div>
      {node.source_segment_ids.length === 0 ? (
        <p className="text-sm text-muted-foreground">No transcript source.</p>
      ) : (
        <ul className="space-y-2" aria-label="Where this step came from">
          {node.source_segment_ids.map((id) => {
            const s = segments.get(id)
            return (
              <li key={id} className="rounded-md border-l-2 border-primary/60 bg-muted/50 px-3 py-2 text-sm">
                {s ? (
                  <>
                    <p className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
                      <Quote className="size-3" aria-hidden />
                      {s.speaker ?? "Unknown"}
                      {s.start_ts != null && ` · ${formatTimestamp(s.start_ts)}`}
                    </p>
                    <p>{s.text}</p>
                  </>
                ) : (
                  <p className="text-muted-foreground">Source text no longer available (retention policy).</p>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

interface ChatLine {
  role: "user" | "assistant" | "error"
  text: string
}

function HistorySheet({ mapId, version }: { mapId: string; version: number }) {
  const { data, isPending } = useQuery({ queryKey: ["versions", mapId, version], queryFn: () => api.versions(mapId) })
  const label = {
    extract: "Extracted",
    chat: "Chat edit",
    visual: "Edited in diagram",
    merge: "Meeting merged",
    resolve: "Conflict resolved",
  }
  return (
    <Sheet>
      <Tooltip>
        <TooltipTrigger asChild>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Version history">
              <History aria-hidden />
            </Button>
          </SheetTrigger>
        </TooltipTrigger>
        <TooltipContent>Version history</TooltipContent>
      </Tooltip>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Version history</SheetTitle>
          <SheetDescription>Every change is a version. Undo steps back one at a time.</SheetDescription>
        </SheetHeader>
        <ScrollArea className="h-[calc(100svh-8rem)] px-4">
          {isPending ? (
            <Skeleton className="h-40" />
          ) : (
            <ol className="space-y-3 pb-6">
              {[...(data ?? [])].reverse().map((v) => (
                <li key={v.version} className="rounded-md border p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">
                      v{v.version} · {label[v.source] ?? v.source}
                    </span>
                    {v.version === version && <Badge>Current</Badge>}
                  </div>
                  {v.instruction && <p className="mt-1 text-muted-foreground">“{v.instruction}”</p>}
                  <p className="mt-1 text-xs text-muted-foreground">{formatDate(v.created_at)}</p>
                </li>
              ))}
            </ol>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}

export function MapEditor() {
  const { mapId = "" } = useParams()
  const qc = useQueryClient()
  const canvas = useRef<BpmnCanvasHandle>(null)
  const [dirty, setDirty] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [tab, setTab] = useState("step")
  const [chat, setChat] = useState<ChatLine[]>([])
  const [instruction, setInstruction] = useState("")
  const ignoreNextChange = useRef(false)

  const query = useQuery({ queryKey: ["map", mapId], queryFn: () => api.map(mapId) })
  const map = query.data

  const setMap = useCallback(
    (next: ProcessMap) => {
      ignoreNextChange.current = true // the import itself fires a change event
      qc.setQueryData(["map", mapId], next)
      setDirty(false)
    },
    [qc, mapId],
  )

  const save = useMutation({
    mutationFn: async () => api.saveBpmn(mapId, await canvas.current!.saveXML()),
    onSuccess: (m) => {
      setMap(m)
      toast.success(`Saved as v${m.version}`)
    },
    onError: (e) => toast.error(`Save failed: ${e.message}`),
  })
  const undo = useMutation({
    mutationFn: () => api.undo(mapId),
    onSuccess: (m) => {
      setMap(m)
      toast.success(`Back to v${m.version}`)
    },
    onError: (e) => toast.error(e.message),
  })
  const send = useMutation({
    mutationFn: async (text: string) => {
      if (dirty) setMap(await api.saveBpmn(mapId, await canvas.current!.saveXML())) // chat edits the saved map
      return api.chat(mapId, text)
    },
    onMutate: (text) => setChat((c) => [...c, { role: "user", text }]),
    onSuccess: (res) => {
      setMap(res)
      setChat((c) => [...c, { role: "assistant", text: res.reply || (res.ops.length ? "Done." : "No changes.") }])
      setInstruction("")
    },
    onError: (e) => setChat((c) => [...c, { role: "error", text: e.message }]),
  })

  // Don't lose unsaved diagram edits: in-app navigation and tab close both ask first.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname,
  )
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [dirty])

  const conflictsById = useMemo(() => new Map((map?.conflicts ?? []).map((c) => [c.id, c])), [map])
  const focusNode = (nodeId: string) => {
    if (!canvas.current?.select(`Node_${nodeId}`) && !canvas.current?.select(nodeId))
      toast.info("That step isn't on the diagram")
    else setTab("step")
  }
  const resolve = async (conflictId: string, option: number | null) => {
    try {
      if (dirty) setMap(await api.saveBpmn(mapId, await canvas.current!.saveXML()))
      await api.resolveConflict(conflictId, option)
      setMap(await api.map(mapId))
      toast.success(option == null ? "Marked as resolved" : "Applied to the map")
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (query.isPending) return <Skeleton className="m-4 h-[70svh] rounded-xl" />
  if (query.error || !map) {
    return (
      <div className="mx-auto max-w-xl p-8 text-sm">
        <p className="font-medium">This map couldn't be opened.</p>
        <p className="mt-1 text-muted-foreground">{query.error?.message}</p>
        <Link to="/projects" className="mt-3 inline-block underline">
          Back to projects
        </Link>
      </div>
    )
  }

  const questions = map.model.open_questions
  return (
    <div className="flex h-[calc(100svh-3.5rem)] flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
        <Button asChild variant="ghost" size="icon" aria-label="Back to project">
          <Link to={`/projects/${map.project_id}`}>
            <ArrowLeft aria-hidden />
          </Link>
        </Button>
        <h1 className="min-w-0 truncate text-base font-semibold">{map.model.name}</h1>
        <Badge variant="outline">v{map.version}</Badge>
        {map.transcript_id == null && <Badge variant="secondary">All meetings</Badge>}
        {dirty && (
          <span className="text-xs text-amber-700 dark:text-amber-300" role="status">
            Unsaved changes
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Fit diagram to screen"
                onClick={() => canvas.current?.zoomToFit()}
              >
                <Maximize aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Fit to screen</TooltipContent>
          </Tooltip>
          <HistorySheet mapId={mapId} version={map.version} />
          <Button variant="outline" onClick={() => undo.mutate()} disabled={!map.can_undo || undo.isPending}>
            {undo.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Undo2 aria-hidden />} Undo
          </Button>
          <ExportMenu mapId={mapId} />
          <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
            {save.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />} Save
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-rows-[minmax(320px,1fr)_auto] lg:grid-cols-[minmax(0,1fr)_400px] lg:grid-rows-1">
        <div className="relative min-h-0 border-b lg:border-b-0 lg:border-r">
          <BpmnCanvas
            ref={canvas}
            xml={map.bpmn_xml}
            onSelect={setSelected}
            onChange={() => {
              if (ignoreNextChange.current) ignoreNextChange.current = false
              else setDirty(true)
            }}
            onImportError={(m) => toast.error(`Couldn't display the diagram: ${m}`)}
          />
        </div>

        <aside className="flex min-h-0 flex-col" aria-label="Map details">
          {map.diarization_available === false && (
            <Alert className="m-3 mb-0">
              <AlertTriangle aria-hidden />
              <AlertDescription>Speakers weren't identified in a recording. Check who does each step.</AlertDescription>
            </Alert>
          )}
          <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
            <TabsList className="mx-3 mt-3 grid w-auto grid-cols-3">
              <TabsTrigger value="step">Step</TabsTrigger>
              <TabsTrigger value="questions">Questions {questions.length > 0 && `(${questions.length})`}</TabsTrigger>
              <TabsTrigger value="issues">Issues {map.errors.length > 0 && `(${map.errors.length})`}</TabsTrigger>
            </TabsList>
            <ScrollArea className="min-h-0 flex-1">
              <div className="p-3">
                <TabsContent value="step">
                  <SelectedStep map={map} xmlId={selected} />
                </TabsContent>
                <TabsContent value="questions" className="space-y-3">
                  {questions.length === 0 && <p className="text-sm text-muted-foreground">No open questions.</p>}
                  {questions.map((q) => {
                    const conflict = q.id.startsWith("conflict_") ? conflictsById.get(q.id.slice(9)) : undefined
                    return conflict ? (
                      <ConflictCard
                        key={q.id}
                        kind={conflict.kind}
                        description={q.question
                          .replace(/^Meetings disagree \(\w+\): /, "")
                          .replace(/ Options: .*$/, "")}
                        options={conflict.options}
                        onResolve={(opt) => resolve(conflict.id, opt)}
                        onSelect={q.related_node_ids[0] ? () => focusNode(q.related_node_ids[0]) : undefined}
                      />
                    ) : (
                      <button
                        key={q.id}
                        type="button"
                        disabled={!q.related_node_ids.length}
                        onClick={() => q.related_node_ids[0] && focusNode(q.related_node_ids[0])}
                        className="block w-full rounded-lg border p-3 text-left text-sm enabled:hover:bg-accent disabled:cursor-default"
                      >
                        {q.question}
                      </button>
                    )
                  })}
                </TabsContent>
                <TabsContent value="issues" className="space-y-2">
                  {map.errors.length === 0 && <p className="text-sm text-muted-foreground">No problems found.</p>}
                  {map.errors.map((e, i) => (
                    <button
                      key={i}
                      type="button"
                      disabled={!e.node_ids.length}
                      onClick={() => e.node_ids[0] && focusNode(e.node_ids[0])}
                      className="flex w-full items-start gap-2 rounded-lg border border-destructive/30 p-3 text-left text-sm enabled:hover:bg-destructive/5"
                    >
                      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
                      {e.message}
                    </button>
                  ))}
                </TabsContent>
              </div>
            </ScrollArea>
          </Tabs>

          <form
            className="space-y-2 border-t p-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (instruction.trim() && !send.isPending) send.mutate(instruction.trim())
            }}
          >
            {chat.length > 0 && (
              <ol className="max-h-36 space-y-1 overflow-y-auto text-sm" aria-live="polite" aria-label="Chat">
                {chat.map((c, i) => (
                  <li
                    key={i}
                    className={
                      c.role === "user" ? "text-muted-foreground" : c.role === "error" ? "text-destructive" : undefined
                    }
                  >
                    {c.role === "user" ? "You: " : ""}
                    {c.text}
                  </li>
                ))}
              </ol>
            )}
            <label htmlFor="chat-input" className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              <MessageSquare className="size-3" aria-hidden /> Describe a change
            </label>
            <div className="flex gap-2">
              <Textarea
                id="chat-input"
                rows={2}
                className="min-h-0 resize-none"
                placeholder="e.g. Finance also checks the VAT number before approving"
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    e.currentTarget.form?.requestSubmit()
                  }
                }}
              />
              <Button
                type="submit"
                size="icon"
                className="h-auto"
                disabled={!instruction.trim() || send.isPending}
                aria-label="Send"
              >
                {send.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <SendHorizontal aria-hidden />}
              </Button>
            </div>
          </form>
        </aside>
      </div>

      <AlertDialog open={blocker.state === "blocked"}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Leave without saving?</AlertDialogTitle>
            <AlertDialogDescription>Your changes to the diagram haven't been saved.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.reset?.()}>Stay</AlertDialogCancel>
            <AlertDialogAction onClick={() => blocker.proceed?.()}>Leave</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
