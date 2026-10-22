import { useQuery } from "@tanstack/react-query"
import { Mic, Square } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { toast } from "sonner"

import { Page } from "@/components/app-shell"
import { BpmnCanvas } from "@/components/bpmn-canvas"
import { PageHeader, Section } from "@/components/dossier"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { formatTimestamp } from "@/lib/format"

/** Live interview: record here; every few minutes one complete recording is sent, transcribed,
 *  and the draft map redrawn. Each chunk is its own MediaRecorder run, so it's a whole file the
 *  server can decode alone (a timeslice of one long recording isn't). */
export function LivePage() {
  const { projectId = "" } = useParams()
  const navigate = useNavigate()
  const [tid, setTid] = useState<string | null>(null)
  const [recording, setRecording] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [sent, setSent] = useState(0)
  const [finishing, setFinishing] = useState(false)
  const stream = useRef<MediaStream | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const started = useRef(0)
  const chunk = useRef({ index: 0, offset: 0 })
  const stopping = useRef(false)

  const live = useQuery({
    queryKey: ["live", tid],
    queryFn: () => api.live(tid!),
    enabled: !!tid,
    refetchInterval: 5000,
  })
  const draft = useQuery({
    queryKey: ["map", live.data?.map_id, live.data?.map_version],
    queryFn: () => api.map(live.data!.map_id!),
    enabled: !!live.data?.map_id,
  })

  useEffect(() => {
    if (!recording) return
    const t = setInterval(() => setElapsed((Date.now() - started.current) / 1000), 1000)
    return () => clearInterval(t)
  }, [recording])

  // Release the microphone if the page is left mid-recording.
  useEffect(() => () => stream.current?.getTracks().forEach((t) => t.stop()), [])

  function recordChunk(transcriptId: string, seconds: number) {
    const rec = new MediaRecorder(stream.current!, { mimeType: "audio/webm" })
    const parts: Blob[] = []
    const { index, offset } = chunk.current
    rec.ondataavailable = (e) => e.data.size && parts.push(e.data)
    rec.onstop = () => {
      const blob = new Blob(parts, { type: "audio/webm" })
      if (blob.size)
        api.liveChunk(transcriptId, index, offset, blob).then(
          () => setSent((n) => n + 1),
          (e: Error) => toast.error(`Chunk ${index + 1} wasn't sent: ${e.message}`),
        )
      if (!stopping.current) {
        chunk.current = { index: index + 1, offset: (Date.now() - started.current) / 1000 }
        recordChunk(transcriptId, seconds)
      }
    }
    rec.start()
    recorder.current = rec
    setTimeout(() => rec.state === "recording" && rec.stop(), seconds * 1000)
  }

  async function start() {
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      toast.error("Microphone access was refused. Allow it in the browser to record.")
      return
    }
    try {
      const l = await api.startLive(projectId)
      setTid(l.transcript_id)
      started.current = Date.now()
      stopping.current = false
      chunk.current = { index: 0, offset: 0 }
      setRecording(true)
      recordChunk(l.transcript_id, l.chunk_seconds)
    } catch (e) {
      stream.current?.getTracks().forEach((t) => t.stop())
      toast.error((e as Error).message)
    }
  }

  async function finish() {
    if (!tid) return
    setFinishing(true)
    stopping.current = true
    const last = recorder.current
    if (last && last.state === "recording") {
      await new Promise<void>((resolve) => {
        last.addEventListener("stop", () => resolve(), { once: true })
        last.stop()
      })
    }
    stream.current?.getTracks().forEach((t) => t.stop())
    setRecording(false)
    await new Promise((r) => setTimeout(r, 1500)) // let the last chunk's upload start first
    try {
      await api.finishLive(tid)
      toast.success("Interview finished", { description: "It's being merged into the process now." })
      navigate(`/projects/${projectId}`)
    } catch (e) {
      toast.error((e as Error).message)
      setFinishing(false)
    }
  }

  const lines = live.data?.lines ?? []
  return (
    <Page>
      <PageHeader
        eyebrow={
          <Link to={`/projects/${projectId}`} className="hover:text-fg">
            ← Process file
          </Link>
        }
        title="Live interview"
        revision={
          tid
            ? `${formatTimestamp(elapsed)} recorded · ${sent} chunk${sent === 1 ? "" : "s"} sent · ${lines.length} lines transcribed${live.data?.map_version ? ` · draft v${live.data.map_version}` : ""}`
            : `Records from this browser's microphone. The draft redraws every ${Math.round((live.data?.chunk_seconds ?? 180) / 60)} minutes or so.`
        }
        actions={
          !tid ? (
            <Button onClick={() => void start()}>
              <Mic aria-hidden /> Start recording
            </Button>
          ) : (
            <Button variant="destructive" onClick={() => void finish()} disabled={finishing}>
              <Square aria-hidden /> {finishing ? "Finishing…" : "Finish interview"}
            </Button>
          )
        }
      />
      {tid && (
        <div className="grid gap-x-10 gap-y-10 lg:grid-cols-[minmax(0,1fr)_360px]">
          <Section title="Draft map" aside={recording ? "Updates after each chunk" : undefined}>
            <div className="h-[60svh] border border-line">
              {draft.data ? (
                <BpmnCanvas
                  xml={draft.data.bpmn_xml}
                  onSelect={() => undefined}
                  onChange={() => undefined}
                  onImportError={() => undefined}
                />
              ) : (
                <p className="p-6 text-fg-muted">The first draft appears after the first chunk is transcribed.</p>
              )}
            </div>
          </Section>
          <Section title="Transcript so far" aside={`${lines.length} lines`}>
            <ol className="max-h-[60svh] space-y-2 overflow-y-auto text-sm" aria-live="polite">
              {lines.map((l) => (
                <li key={l.segment_id}>
                  <span className="label mr-1.5">
                    {l.speaker ?? "Speaker"} {l.start_ts != null && formatTimestamp(l.start_ts)}
                  </span>
                  {l.text}
                </li>
              ))}
              {lines.length === 0 && <li className="text-fg-muted">Listening…</li>}
            </ol>
          </Section>
        </div>
      )}
    </Page>
  )
}
