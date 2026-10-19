import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronLeft, History, Maximize, PanelRightClose, PanelRightOpen, Sparkles } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useBlocker, useParams } from "react-router"
import { toast } from "sonner"

import { BpmnCanvas, type BpmnCanvasHandle, type Dispute } from "@/components/bpmn-canvas"
import { ConflictPoint } from "@/components/conflict-card"
import { Chip, Empty, Quote } from "@/components/kit"
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
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api, downloadText, isStale } from "@/lib/api"
import { formatDate } from "@/lib/format"
import type { ProcessMap, ProcessNode, Resolution } from "@/lib/types"
import { cn } from "@/lib/utils"
import { ExportMenu } from "@/pages/project"

/** Our exports use `Node_<id>`; elements created in the editor keep their bpmn-js id. */
function modelNodeId(map: ProcessMap, xmlId: string): string | null {
  const ids = new Set(map.model.nodes.map((n) => n.id))
  const stripped = xmlId.replace(/^Node_/, "")
  return ids.has(stripped) ? stripped : ids.has(xmlId) ? xmlId : null
}

const NODE_TYPE_LABEL: Record<ProcessNode["type"], string> = {
  start_event: "Start",
  end_event: "Outcome",
  user_task: "Step · done by a person",
  service_task: "Step · done by a system",
  exclusive_gateway: "Decision",
  parallel_gateway: "Parallel work",
}

/** Which transcript a merged-map citation (`<transcript_id>:s3`) came from, if any. */
const meetingOf = (segmentId: string) => (segmentId.includes(":") ? segmentId.split(":")[0] : null)

function SelectedStep({
  map,
  xmlId,
  points,
}: {
  map: ProcessMap
  xmlId: string | null
  points: Map<string, number[]>
}) {
  if (!xmlId) return <Empty title="Select a step on the map">to read where it came from.</Empty>
  const nodeId = modelNodeId(map, xmlId)
  const node = map.model.nodes.find((n) => n.id === nodeId)
  if (!node) return <p className="py-2 text-sm text-fg-muted">Not saved yet. Save to keep this element.</p>
  const lane = map.model.lanes.find((l) => l.id === node.lane_id)
  const segments = new Map(map.segments.map((s) => [s.segment_id, s]))
  const meetings = [...new Set(node.source_segment_ids.map(meetingOf).filter(Boolean))]
  const disputed = points.get(node.id)
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <p className="eyebrow">{NODE_TYPE_LABEL[node.type]}</p>
        <h3 className="text-lg leading-snug">{node.name || "(unnamed)"}</h3>
        <div className="flex flex-wrap gap-1.5">
          <Chip>{lane?.name ?? node.lane_id}</Chip>
          {node.user_added && <Chip>Added by hand</Chip>}
          {!node.user_added && node.confidence < 0.6 && (
            <Chip tone="warn">Low confidence · {Math.round(node.confidence * 100)}%</Chip>
          )}
          {meetings.length > 1 && <Chip tone="info">In {meetings.length} meetings</Chip>}
          {disputed && <Chip tone="warn">In dispute: {disputed.map((n) => `D${n}`).join(", ")}</Chip>}
        </div>
      </div>
      <div>
        <p className="eyebrow mb-2">Sources</p>
        {node.source_segment_ids.length === 0 ? (
          <p className="text-sm text-fg-muted">No transcript source: this step was added by hand.</p>
        ) : (
          <ol className="space-y-3" aria-label="Where this step came from">
            {node.source_segment_ids.map((id, i) => {
              const s = segments.get(id)
              return (
                <li key={id}>
                  <Quote
                    index={i + 1}
                    q={{
                      text: s?.text ?? null,
                      speaker: s?.speaker ?? null,
                      role: null,
                      meeting: "",
                      start_ts: s?.start_ts ?? null,
                      policy: false,
                    }}
                  />
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </div>
  )
}

interface ChatLine {
  role: "user" | "assistant" | "error"
  text: string
}

const SOURCE_LABEL = {
  extract: "Drafted from a meeting",
  chat: "Edited by instruction",
  visual: "Edited on the diagram",
  merge: "Meeting merged in",
  resolve: "Point settled",
}

function readPref(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}
function writePref(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* a per-browser convenience only */
  }
}
const clampWidth = (w: number) => Math.min(640, Math.max(320, Number.isFinite(w) ? w : 400))

/** Drag (or arrow keys) to resize the inspector. */
function Resizer({ width, onWidth }: { width: number; onWidth: (w: number) => void }) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the inspector"
      aria-valuenow={width}
      aria-valuemin={320}
      aria-valuemax={640}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") onWidth(clampWidth(width + 24))
        if (e.key === "ArrowRight") onWidth(clampWidth(width - 24))
      }}
      onPointerDown={(e) => {
        const startX = e.clientX
        const start = width
        const move = (ev: PointerEvent) => onWidth(clampWidth(start + startX - ev.clientX))
        const up = () => {
          window.removeEventListener("pointermove", move)
          window.removeEventListener("pointerup", up)
        }
        window.addEventListener("pointermove", move)
        window.addEventListener("pointerup", up)
      }}
      className="group absolute inset-y-0 -left-1.5 z-10 hidden w-3 cursor-col-resize lg:block"
    >
      <span className="transition-quiet absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line group-hover:bg-brand group-focus-visible:bg-brand" />
    </div>
  )
}

function HistorySheet({ mapId, version }: { mapId: string; version: number }) {
  const { data, isPending } = useQuery({ queryKey: ["versions", mapId, version], queryFn: () => api.versions(mapId) })
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
      <SheetContent className="bg-panel">
        <SheetHeader>
          <SheetTitle className="text-lg">Version history</SheetTitle>
          <SheetDescription>Every change is kept. Undo steps back one at a time.</SheetDescription>
        </SheetHeader>
        <ScrollArea className="h-[calc(100svh-8rem)] px-4">
          {isPending ? (
            <Skeleton className="h-40 bg-raised" />
          ) : (
            <ol className="pb-6">
              {[...(data ?? [])].reverse().map((v) => (
                <li key={v.version} className="grid grid-cols-[3rem_1fr] gap-x-3 border-b border-line py-3">
                  <span className="tabular text-sm font-semibold text-fg-muted">v{v.version}</span>
                  <div>
                    <p className="flex items-center gap-2 text-sm font-medium">
                      {SOURCE_LABEL[v.source] ?? v.source}
                      {v.version === version && <Chip tone="info">Current</Chip>}
                    </p>
                    {v.instruction && <p className="mt-0.5 text-sm text-fg">“{v.instruction}”</p>}
                    <p className="tabular mt-0.5 text-xs text-fg-subtle">{formatDate(v.created_at)}</p>
                  </div>
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
  const [inspector, setInspector] = useState(() => readPref("t2b_inspector", "open") !== "closed")
  const [width, setWidth] = useState(() => clampWidth(Number(readPref("t2b_inspector_w", "400"))))
  const [chat, setChat] = useState<ChatLine[]>([])
  const [instruction, setInstruction] = useState("")
  const ignoreNextChange = useRef(false)

  const query = useQuery({ queryKey: ["map", mapId], queryFn: () => api.map(mapId) })
  const map = query.data
  // Set when the server has a newer version than this editor (someone else edited).
  const [stale, setStale] = useState<string | null>(null) // message of a refused (412) edit

  // Check for edits made elsewhere (another person, a meeting being merged) every 15 s.
  const remote = useQuery({
    queryKey: ["map-remote", mapId],
    queryFn: () => api.map(mapId),
    refetchInterval: 15_000,
    enabled: !!map,
  })

  const setMap = useCallback(
    (next: ProcessMap) => {
      ignoreNextChange.current = true // the import itself fires a change event
      qc.setQueryData(["map", mapId], next)
      setDirty(false)
    },
    [qc, mapId],
  )

  /** A 412 means our version is behind: stop and let the user choose (never overwrite). */
  const failed = (e: Error, prefix = "") => {
    if (isStale(e)) setStale(e.message)
    else toast.error(prefix + e.message)
  }
  /** Save pending diagram edits first; returns the version later requests must build on. */
  const saveIfDirty = async (): Promise<number> => {
    if (!dirty) return map!.version
    const saved = await api.saveBpmn(mapId, await canvas.current!.saveXML(), map!.version)
    setMap(saved)
    return saved.version
  }

  const save = useMutation({
    mutationFn: async () => api.saveBpmn(mapId, await canvas.current!.saveXML(), map!.version),
    onSuccess: (m) => {
      setMap(m)
      toast.success(`Saved as v${m.version}`)
    },
    onError: (e) => failed(e, "Save failed: "),
  })
  const undo = useMutation({
    mutationFn: () => api.undo(mapId, map!.version),
    onSuccess: (m) => {
      setMap(m)
      toast.success(`Back to v${m.version}`)
    },
    onError: (e) => failed(e),
  })
  const send = useMutation({
    mutationFn: async (text: string) => api.chat(mapId, text, await saveIfDirty()), // chat edits the saved map
    onMutate: (text) => setChat((c) => [...c, { role: "user", text }]),
    onSuccess: (res) => {
      setMap(res)
      setChat((c) => [...c, { role: "assistant", text: res.reply || (res.ops.length ? "Done." : "No changes.") }])
      setInstruction("")
    },
    onError: (e) => {
      if (isStale(e)) failed(e)
      setChat((c) => [
        ...c,
        { role: "error", text: isStale(e) ? "Not applied: the map changed elsewhere." : e.message },
      ])
    },
  })

  // Newer version on the server: adopt it silently if nothing local would be lost; with
  // unsaved edits, show a banner instead (derived here, not stored).
  const newerElsewhere = remote.data && map && remote.data.version > map.version ? remote.data : null
  useEffect(() => {
    if (!newerElsewhere || dirty) return
    ignoreNextChange.current = true // the re-import fires a change event
    qc.setQueryData(["map", mapId], newerElsewhere)
    toast.info(`Updated to v${newerElsewhere.version}: this map was changed elsewhere`)
  }, [newerElsewhere, dirty, qc, mapId])

  const reloadLatest = async () => {
    setStale(null)
    setMap(await api.map(mapId))
  }
  const downloadMine = async () => {
    downloadText(await canvas.current!.saveXML(), `${map!.model.name.replace(/[^\w-]+/g, "_")}-my-changes.bpmn`)
  }

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
  // Who said what on each side (the map payload only carries ids and options).
  const fullConflicts = useQuery({
    queryKey: ["conflicts", map?.project_id, "open-meeting", map?.version],
    queryFn: () => api.conflicts(map!.project_id, { status: "open", origin: "meeting" }),
    enabled: !!map && !map.transcript_id,
  })
  const evidence = useMemo(() => new Map((fullConflicts.data ?? []).map((c) => [c.id, c])), [fullConflicts.data])
  // Disagreements are D1, D2, … in question order (as on the process page); the same id marks
  // the steps involved on the diagram.
  const { disputes, pointOf } = useMemo(() => {
    const byNode = new Map<string, number[]>()
    const byQuestion = new Map<string, number>()
    for (const q of map?.model.open_questions ?? []) {
      if (!q.id.startsWith("conflict_") || !conflictsById.has(q.id.slice(9))) continue
      const n = byQuestion.size + 1
      byQuestion.set(q.id, n)
      for (const nodeId of q.related_node_ids) byNode.set(nodeId, [...(byNode.get(nodeId) ?? []), n])
    }
    return { disputes: byNode, pointOf: byQuestion }
  }, [map, conflictsById])
  const canvasDisputes: Dispute[] = useMemo(
    () => [...disputes].map(([nodeId, nums]) => ({ nodeId, label: nums.map((n) => `D${n}`).join(" ") })),
    [disputes],
  )
  const focusNode = (nodeId: string) => {
    if (!canvas.current?.select(`Node_${nodeId}`) && !canvas.current?.select(nodeId))
      toast.info("That step isn't on the diagram")
    else setTab("step")
  }
  const resolve = async (conflictId: string, how: Resolution) => {
    try {
      await api.resolveConflict(conflictId, how, await saveIfDirty())
      setMap(await api.map(mapId))
      toast.success("option" in how || "variant" in how ? "Applied to the map" : "Marked as settled")
    } catch (e) {
      failed(e as Error)
    }
  }

  if (query.isPending) return <Skeleton className="m-6 h-[70svh] rounded-lg bg-panel" />
  if (query.error || !map) {
    return (
      <div className="mx-auto max-w-lg p-10">
        <p className="text-lg font-semibold">This map couldn't be opened.</p>
        <p className="mt-1 text-fg-muted">{query.error?.message}</p>
        <Link to="/" className="mt-3 inline-block text-brand hover:underline">
          Back to the inbox
        </Link>
      </div>
    )
  }

  const questions = map.model.open_questions
  const toggleInspector = () => {
    writePref("t2b_inspector", inspector ? "closed" : "open")
    setInspector(!inspector)
  }
  const resize = (w: number) => {
    setWidth(w)
    writePref("t2b_inspector_w", String(w))
  }
  const lastReply = [...chat].reverse().find((c) => c.role !== "user")
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-14 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-panel px-4 py-2">
        <Button asChild variant="ghost" size="icon-sm" aria-label="Back to the process">
          <Link to={`/projects/${map.project_id}`}>
            <ChevronLeft aria-hidden />
          </Link>
        </Button>
        <div className="min-w-0">
          <h1 className="truncate text-base">{map.model.name}</h1>
          <p className="tabular text-xs text-fg-muted" role="status">
            v{map.version}
            {map.transcript_id == null ? " · all meetings" : " · this meeting only"}
            {dirty && <span className="text-warn"> · unsaved changes</span>}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
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
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label={inspector ? "Hide the inspector" : "Show the inspector"}
                aria-pressed={inspector}
                onClick={toggleInspector}
              >
                {inspector ? <PanelRightClose aria-hidden /> : <PanelRightOpen aria-hidden />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{inspector ? "Hide inspector" : "Show inspector"}</TooltipContent>
          </Tooltip>
          <Button variant="outline" onClick={() => undo.mutate()} disabled={!map.can_undo || undo.isPending}>
            {undo.isPending ? "Undoing…" : "Undo"}
          </Button>
          <ExportMenu mapId={mapId} />
          <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>

      {newerElsewhere && dirty && !stale && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-3 border-b border-warn/30 bg-warn-tint px-4 py-2.5 text-sm"
        >
          <span>
            Someone else saved <strong>v{newerElsewhere.version}</strong> while you were editing v{map.version}. Saving
            now would be refused.
          </span>
          <Button size="sm" variant="outline" onClick={() => void downloadMine()}>
            Download my version
          </Button>
          <Button size="sm" onClick={() => void reloadLatest()}>
            Reload latest
          </Button>
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* the diagram sits on a light sheet, like the export people will see */}
        <div className="relative min-h-[420px] flex-1 p-3">
          <div className="relative h-full overflow-hidden rounded-lg border border-line bg-sheet">
            <BpmnCanvas
              ref={canvas}
              xml={map.bpmn_xml}
              disputes={canvasDisputes}
              onSelect={(id) => {
                setSelected(id)
                if (id) setTab("step")
              }}
              onChange={() => {
                if (ignoreNextChange.current) ignoreNextChange.current = false
                else setDirty(true)
              }}
              onImportError={(m) => toast.error(`Couldn't display the diagram: ${m}`)}
            />
          </div>

          <form
            className="absolute bottom-6 left-1/2 z-10 w-[min(680px,calc(100%-3rem))] -translate-x-1/2"
            onSubmit={(e) => {
              e.preventDefault()
              if (instruction.trim() && !send.isPending) send.mutate(instruction.trim())
            }}
          >
            {lastReply && (
              <p
                aria-live="polite"
                className={cn(
                  "mb-2 rounded-md border border-line bg-raised px-3 py-2 text-sm shadow-lg",
                  lastReply.role === "error" ? "text-bad" : "text-fg",
                )}
              >
                {lastReply.text}
              </p>
            )}
            <div className="flex items-center gap-2 rounded-lg border border-line-strong bg-raised p-1.5 pl-3 shadow-xl">
              <Sparkles className="size-4 shrink-0 text-brand" aria-hidden />
              <label htmlFor="chat-input" className="sr-only">
                Describe a change
              </label>
              <input
                id="chat-input"
                className="h-9 min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
                placeholder="Describe a change, e.g. Finance also checks the VAT number before approving"
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                autoComplete="off"
              />
              <Button type="submit" size="sm" disabled={!instruction.trim() || send.isPending}>
                {send.isPending ? "Applying…" : "Apply"}
              </Button>
            </div>
          </form>
        </div>

        {inspector && (
          <aside
            className="relative flex min-h-[360px] flex-col border-t border-line bg-panel lg:min-h-0 lg:w-[var(--inspector-w)] lg:shrink-0 lg:border-t-0 lg:border-l"
            style={{ "--inspector-w": `${width}px` } as React.CSSProperties}
            aria-label="Inspector"
          >
            <div className="flex min-h-0 flex-1 flex-col">
              <Resizer width={width} onWidth={resize} />
              {map.diarization_available === false && (
                <p className="border-b border-line bg-warn-tint px-4 py-2.5 text-sm text-fg">
                  Speakers weren't identified in a recording. Check who does each step.
                </p>
              )}
              <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col gap-0">
                <TabsList
                  variant="line"
                  className="h-11 w-full justify-start gap-1 rounded-none border-b border-line px-3"
                >
                  {(
                    [
                      ["step", "Step", 0],
                      ["questions", "Questions", questions.length],
                      ["issues", "Issues", map.errors.length],
                    ] as const
                  ).map(([value, label, count]) => (
                    <TabsTrigger
                      key={value}
                      value={value}
                      className="h-11 flex-none rounded-none px-2.5 text-fg-muted data-[state=active]:text-fg group-data-[variant=line]/tabs-list:data-active:after:bg-brand"
                    >
                      {label}
                      {count > 0 && (
                        <span className="tabular rounded-md bg-raised px-1.5 text-xs text-fg-muted">{count}</span>
                      )}
                    </TabsTrigger>
                  ))}
                </TabsList>
                <ScrollArea className="min-h-0 flex-1">
                  <div className="p-4">
                    <TabsContent value="step">
                      <SelectedStep map={map} xmlId={selected} points={disputes} />
                    </TabsContent>
                    <TabsContent value="questions">
                      {questions.length === 0 && <Empty title="No open questions" />}
                      <div className="space-y-5">
                        {questions.map((q) => {
                          const conflict = q.id.startsWith("conflict_") ? conflictsById.get(q.id.slice(9)) : undefined
                          return conflict ? (
                            <ConflictPoint
                              key={q.id}
                              compact
                              itemId={`D${pointOf.get(q.id) ?? 0}`}
                              conflict={
                                evidence.get(conflict.id) ?? {
                                  ...conflict,
                                  description: q.question
                                    .replace(/^Meetings disagree \(\w+\): /, "")
                                    .replace(/ Options: .*$/, ""),
                                }
                              }
                              onResolve={(how) => resolve(conflict.id, how)}
                              onSelect={q.related_node_ids[0] ? () => focusNode(q.related_node_ids[0]) : undefined}
                            />
                          ) : (
                            <button
                              key={q.id}
                              type="button"
                              disabled={!q.related_node_ids.length}
                              onClick={() => q.related_node_ids[0] && focusNode(q.related_node_ids[0])}
                              className="block w-full rounded-md py-2 text-left text-sm leading-relaxed enabled:hover:text-brand disabled:cursor-default"
                            >
                              {q.question}
                            </button>
                          )
                        })}
                      </div>
                    </TabsContent>
                    <TabsContent value="issues">
                      {map.errors.length === 0 && <Empty title="No structural problems found" />}
                      <ol className="divide-y divide-line">
                        {map.errors.map((e, i) => (
                          <li key={i}>
                            <button
                              type="button"
                              disabled={!e.node_ids.length}
                              onClick={() => e.node_ids[0] && focusNode(e.node_ids[0])}
                              className="grid w-full grid-cols-[1.5rem_1fr] rounded-md px-1 py-3 text-left text-sm enabled:hover:bg-raised disabled:cursor-default"
                            >
                              <span className="tabular text-fg-subtle">{i + 1}.</span>
                              {e.message}
                            </button>
                          </li>
                        ))}
                      </ol>
                    </TabsContent>
                  </div>
                </ScrollArea>
              </Tabs>
            </div>
          </aside>
        )}
      </div>

      <AlertDialog open={!!stale}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Someone else changed this map</AlertDialogTitle>
            <AlertDialogDescription>
              {stale} Nothing was overwritten. Reload to continue from the latest version
              {dirty ? "; download your unsaved changes first if you want to keep them" : ""}.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            {dirty && (
              <Button variant="outline" onClick={() => void downloadMine()}>
                Download my version
              </Button>
            )}
            <AlertDialogAction onClick={() => void reloadLatest()}>Reload latest</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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
