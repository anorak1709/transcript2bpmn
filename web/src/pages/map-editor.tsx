import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { History, Maximize, MoreHorizontal, TriangleAlert, X } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useBlocker, useParams } from "react-router"
import { toast } from "sonner"

import { BpmnCanvas, type BpmnCanvasHandle, type Dispute } from "@/components/bpmn-canvas"
import { ConflictPoint } from "@/components/conflict-card"
import { SourceQuote } from "@/components/dossier"
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
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { api, downloadText, isStale } from "@/lib/api"
import { formatDate, formatTimestamp, roman } from "@/lib/format"
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
  if (!xmlId)
    return <p className="py-2 text-[1.05rem] text-graphite">Select a step on the map to read where it came from.</p>
  const nodeId = modelNodeId(map, xmlId)
  const node = map.model.nodes.find((n) => n.id === nodeId)
  if (!node) return <p className="py-2 text-sm text-graphite">Not saved yet. Save to keep this element.</p>
  const lane = map.model.lanes.find((l) => l.id === node.lane_id)
  const segments = new Map(map.segments.map((s) => [s.segment_id, s]))
  const meetings = [...new Set(node.source_segment_ids.map(meetingOf).filter(Boolean))]
  const disputed = points.get(node.id)
  return (
    <div className="space-y-5">
      <div>
        <p className="label">{NODE_TYPE_LABEL[node.type]}</p>
        <h3 className="mt-1 text-2xl leading-tight">{node.name || "(unnamed)"}</h3>
        <p className="mt-1 text-sm text-graphite">
          {lane?.name ?? node.lane_id}
          {node.user_added
            ? " · added by hand"
            : node.confidence < 0.6
              ? ` · low confidence (${Math.round(node.confidence * 100)}%)`
              : ""}
          {meetings.length > 1 ? ` · described in ${meetings.length} meetings` : ""}
        </p>
        {disputed && (
          <p className="mt-2 text-sm text-oxblood">
            In dispute: see point{disputed.length > 1 ? "s" : ""} {disputed.map((n) => `${roman(n)}.`).join(", ")}
          </p>
        )}
      </div>
      <div>
        <p className="label mb-2 border-b border-hairline pb-1">Sources</p>
        {node.source_segment_ids.length === 0 ? (
          <p className="text-sm text-graphite">No transcript source: this step was added by hand.</p>
        ) : (
          <ol className="space-y-4" aria-label="Where this step came from">
            {node.source_segment_ids.map((id, i) => {
              const s = segments.get(id)
              return (
                <li key={id}>
                  {s ? (
                    <SourceQuote
                      index={i + 1}
                      speaker={s.speaker ?? "Unknown speaker"}
                      when={s.start_ts != null ? formatTimestamp(s.start_ts) : undefined}
                      text={s.text}
                    />
                  ) : (
                    <p className="text-sm text-graphite">
                      {i + 1}. Source text no longer available (deleted by the retention policy).
                    </p>
                  )}
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

function HistorySheet({
  mapId,
  version,
  open,
  onOpenChange,
}: {
  mapId: string
  version: number
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const { data, isPending } = useQuery({
    queryKey: ["versions", mapId, version],
    queryFn: () => api.versions(mapId),
    enabled: open,
  })
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="bg-paper">
        <SheetHeader>
          <SheetTitle className="text-2xl font-bold">Revisions</SheetTitle>
          <SheetDescription className="text-graphite">
            Every change is kept. Undo steps back one at a time.
          </SheetDescription>
        </SheetHeader>
        <ScrollArea className="h-[calc(100svh-8rem)] px-4">
          {isPending ? (
            <Skeleton className="h-40 bg-paper-shade" />
          ) : (
            <ol className="pb-6">
              {[...(data ?? [])].reverse().map((v) => (
                <li key={v.version} className="grid grid-cols-[3rem_1fr] gap-x-3 border-b border-hairline py-3">
                  <span className="tabular text-lg">v{v.version}</span>
                  <div>
                    <p className="text-sm font-bold">
                      {SOURCE_LABEL[v.source] ?? v.source}
                      {v.version === version && <span className="ml-2 font-normal text-graphite">current</span>}
                    </p>
                    {v.instruction && <p className="mt-0.5 text-[1.02rem]">“{v.instruction}”</p>}
                    <p className="tabular mt-0.5 text-xs text-graphite">{formatDate(v.created_at)}</p>
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
  // Canvas first: the side panel only opens for a selected step, the questions or the issues.
  const [panel, setPanel] = useState<"step" | "questions" | "issues" | null>(null)
  const [history, setHistory] = useState(false)
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
  // Disagreements are numbered i., ii., … in question order; the same numeral marks the steps
  // involved on the diagram.
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
    () => [...disputes].map(([nodeId, nums]) => ({ nodeId, label: nums.map(roman).join(" ") })),
    [disputes],
  )
  const focusNode = (nodeId: string) => {
    if (!canvas.current?.select(`Node_${nodeId}`) && !canvas.current?.select(nodeId))
      toast.info("That step isn't on the diagram")
    else setPanel("step")
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

  if (query.isPending) return <Skeleton className="m-6 h-[70svh] rounded-sm bg-paper-shade" />
  if (query.error || !map) {
    return (
      <div className="measure mx-auto p-10">
        <p className="text-2xl">This map couldn't be opened.</p>
        <p className="mt-1 text-graphite">{query.error?.message}</p>
        <Link to="/projects" className="mt-3 inline-block underline">
          Back to the index
        </Link>
      </div>
    )
  }

  const questions = map.model.open_questions
  const reply = [...chat].reverse().find((c) => c.role !== "user")
  return (
    <div className="flex h-[calc(100svh-3.5rem)] flex-col bg-paper">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-6 py-3">
        <div className="min-w-0">
          <Link
            to={`/projects/${map.project_id}`}
            className="label inline-flex min-h-6 items-center text-graphite hover:text-ink"
          >
            ← {map.transcript_id == null ? "Process file" : "Meeting map"}
          </Link>
          <h1 className="truncate text-[1.25rem] leading-tight">
            {map.model.name}
            <span className="tabular ml-3 text-sm font-normal text-graphite" role="status">
              v{map.version}
              {map.transcript_id == null ? " · all meetings" : " · this meeting only"}
              {dirty && <span className="text-ink"> · unsaved changes</span>}
            </span>
          </h1>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <Button
            variant="ghost"
            aria-pressed={panel === "questions"}
            onClick={() => setPanel(panel === "questions" ? null : "questions")}
          >
            Questions{questions.length > 0 && <span className="tabular text-oxblood">{questions.length}</span>}
          </Button>
          <Button variant="outline" onClick={() => undo.mutate()} disabled={!map.can_undo || undo.isPending}>
            {undo.isPending ? "Undoing…" : "Undo"}
          </Button>
          <ExportMenu mapId={mapId} />
          <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="More">
                <MoreHorizontal aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => canvas.current?.zoomToFit()}>
                <Maximize aria-hidden /> Fit to screen
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setHistory(true)}>
                <History aria-hidden /> Version history
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setPanel("issues")}>
                <TriangleAlert aria-hidden /> Issues{map.errors.length ? ` (${map.errors.length})` : ""}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <HistorySheet mapId={mapId} version={map.version} open={history} onOpenChange={setHistory} />

      {newerElsewhere && dirty && !stale && (
        <div role="status" className="flex flex-wrap items-center gap-3 bg-oxblood-tint px-6 py-2.5 text-sm">
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
        <div className="flex min-h-[360px] min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1 overflow-hidden border-y border-hairline">
            <BpmnCanvas
              ref={canvas}
              xml={map.bpmn_xml}
              disputes={canvasDisputes}
              onSelect={(id) => {
                setSelected(id)
                if (id) setPanel("step")
                else setPanel((p) => (p === "step" ? null : p))
              }}
              onChange={() => {
                if (ignoreNextChange.current) ignoreNextChange.current = false
                else setDirty(true)
              }}
              onImportError={(m) => toast.error(`Couldn't display the diagram: ${m}`)}
            />
          </div>
          <form
            className="flex flex-wrap items-center gap-x-3 gap-y-1 px-6 py-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (instruction.trim() && !send.isPending) send.mutate(instruction.trim())
            }}
          >
            <label htmlFor="chat-input" className="sr-only">
              Describe a change
            </label>
            <Input
              id="chat-input"
              className="min-w-0 flex-1"
              placeholder="Describe a change, e.g. Finance also checks the VAT number before approving"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              autoComplete="off"
            />
            <Button type="submit" variant="outline" disabled={!instruction.trim() || send.isPending}>
              {send.isPending ? "Applying…" : "Apply"}
            </Button>
            {reply && (
              <p
                aria-live="polite"
                className={cn("w-full text-sm", reply.role === "error" ? "text-oxblood" : "text-graphite")}
              >
                {reply.text}
              </p>
            )}
          </form>
        </div>

        {panel && (
          <aside className="flex min-h-0 flex-col border-hairline lg:w-[420px] lg:border-l" aria-label="Map details">
            <div className="flex items-center gap-1 px-4 pt-3">
              {(
                [
                  ["step", "Step"],
                  ["questions", "Questions"],
                  ["issues", "Issues"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={panel === value}
                  onClick={() => setPanel(value)}
                  className={cn(
                    "transition-quiet inline-flex h-8 items-center rounded-sm px-2.5 text-sm",
                    panel === value ? "bg-paper-shade font-bold text-ink" : "text-graphite hover:text-ink",
                  )}
                >
                  {label}
                </button>
              ))}
              <Button
                variant="ghost"
                size="icon"
                className="ml-auto"
                aria-label="Close panel"
                onClick={() => setPanel(null)}
              >
                <X aria-hidden />
              </Button>
            </div>
            {map.diarization_available === false && (
              <p className="px-6 pt-3 text-sm text-graphite">
                Speakers weren't identified in a recording. Check who does each step.
              </p>
            )}
            <ScrollArea className="min-h-0 flex-1">
              <div className="px-6 py-5">
                {panel === "step" && <SelectedStep map={map} xmlId={selected} points={disputes} />}
                {panel === "questions" && (
                  <>
                    {questions.length === 0 && <p className="text-graphite">No open questions.</p>}
                    <div className="divide-y divide-hairline">
                      {questions.map((q) => {
                        const conflict = q.id.startsWith("conflict_") ? conflictsById.get(q.id.slice(9)) : undefined
                        return conflict ? (
                          <ConflictPoint
                            key={q.id}
                            number={pointOf.get(q.id) ?? 0}
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
                            className="block w-full py-4 text-left leading-snug enabled:hover:text-ink disabled:cursor-default"
                          >
                            {q.question}
                          </button>
                        )
                      })}
                    </div>
                  </>
                )}
                {panel === "issues" && (
                  <>
                    {map.errors.length === 0 && <p className="text-graphite">No structural problems found.</p>}
                    <ol className="divide-y divide-hairline">
                      {map.errors.map((e, i) => (
                        <li key={i}>
                          <button
                            type="button"
                            disabled={!e.node_ids.length}
                            onClick={() => e.node_ids[0] && focusNode(e.node_ids[0])}
                            className="grid w-full grid-cols-[1.5rem_1fr] py-3 text-left text-sm enabled:hover:text-ink disabled:cursor-default"
                          >
                            <span className="tabular text-graphite">{i + 1}.</span>
                            {e.message}
                          </button>
                        </li>
                      ))}
                    </ol>
                  </>
                )}
              </div>
            </ScrollArea>
          </aside>
        )}
      </div>

      <AlertDialog open={!!stale}>
        <AlertDialogContent className="bg-sheet">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-2xl">Someone else changed this map</AlertDialogTitle>
            <AlertDialogDescription className="text-graphite">
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
        <AlertDialogContent className="bg-sheet">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-2xl">Leave without saving?</AlertDialogTitle>
            <AlertDialogDescription className="text-graphite">
              Your changes to the diagram haven't been saved.
            </AlertDialogDescription>
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
