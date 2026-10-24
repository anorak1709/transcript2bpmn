import "bpmn-js/dist/assets/diagram-js.css"
import "bpmn-js/dist/assets/bpmn-js.css"
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css" // font files, not data: URLs (CSP)
import "./bpmn-canvas.css"

import BpmnModeler from "bpmn-js/lib/Modeler"
import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react"

// The handful of diagram-js services the editor uses, typed narrowly.
interface Viewbox {
  x: number
  y: number
  width: number
  height: number
}
interface DiagramElement {
  id: string
  type: string
}
interface CanvasService {
  viewbox(): Viewbox
  viewbox(box: Viewbox): void
  zoom(level: "fit-viewport" | number): void
  resized(): void
  scrollToElement(element: DiagramElement): void
  addMarker(id: string, cls: string): void
  removeMarker(id: string, cls: string): void
}
interface Services {
  canvas: CanvasService
  elementRegistry: { get(id: string): DiagramElement | undefined }
  selection: { select(element: DiagramElement): void }
  overlays: {
    add(id: string, type: string, o: { position: { top?: number; right?: number }; html: HTMLElement }): string
    remove(filter: { type: string }): void
  }
}

/** A step in dispute, marked on the diagram with its point numeral (e.g. "ii"). */
export interface Dispute {
  nodeId: string
  label: string
}

export interface BpmnCanvasHandle {
  saveXML(): Promise<string>
  select(xmlId: string): boolean
  zoomToFit(): void
}

// MASTER "themed to match": carbon ink on white shapes over paper, Inter labels (hex: bpmn-js needs literals). Rendering only: the saved
// XML and server-side exports keep standard BPMN styling.
const FONT = '"Inter Variable", "Inter", system-ui, sans-serif'
const THEME = {
  bpmnRenderer: { defaultFillColor: "#ffffff", defaultStrokeColor: "#111111", defaultLabelColor: "#111111" },
  textRenderer: {
    defaultStyle: { fontFamily: FONT, fontSize: 14, fontWeight: 500, lineHeight: 1.15 },
    externalStyle: { fontFamily: FONT, fontSize: 13, fontWeight: 500, lineHeight: 1.15 },
  },
}
const DISPUTED = "t2b-disputed"

// Labels are measured when drawn, so draw only once the font has actually loaded.
const fontReady: Promise<unknown> = document.fonts
  ? document.fonts.load(`500 14px ${FONT}`).catch(() => undefined)
  : Promise.resolve()

export const BpmnCanvas = forwardRef<
  BpmnCanvasHandle,
  {
    xml: string
    disputes?: Dispute[]
    onSelect: (xmlId: string | null) => void
    onChange: () => void
    onImportError: (message: string) => void
  }
>(function BpmnCanvas({ xml, disputes, onSelect, onChange, onImportError }, ref) {
  const container = useRef<HTMLDivElement>(null)
  const modeler = useRef<BpmnModeler | null>(null)
  const latest = useRef({ onSelect, onChange, onImportError, disputes: disputes ?? [] })
  useLayoutEffect(() => {
    latest.current = { onSelect, onChange, onImportError, disputes: disputes ?? [] } // for bpmn-js callbacks
  })
  const imported = useRef(false)
  const marked = useRef<string[]>([])

  const svc = <K extends keyof Services>(name: K): Services[K] => modeler.current!.get(name) as Services[K]

  /** Oxblood outline + numeral on each disputed step (MASTER: the same numeral as the list). */
  const markDisputes = () => {
    if (!modeler.current || !imported.current) return
    const canvas = svc("canvas")
    for (const id of marked.current) canvas.removeMarker(id, DISPUTED)
    svc("overlays").remove({ type: DISPUTED })
    marked.current = []
    for (const d of latest.current.disputes) {
      const el = svc("elementRegistry").get(`Node_${d.nodeId}`) ?? svc("elementRegistry").get(d.nodeId)
      if (!el) continue
      canvas.addMarker(el.id, DISPUTED)
      const mark = document.createElement("span")
      mark.className = "t2b-dispute-mark"
      mark.textContent = d.label
      mark.title = `In dispute: point ${d.label}`
      svc("overlays").add(el.id, DISPUTED, { position: { top: -11, right: 12 }, html: mark })
      marked.current.push(el.id)
    }
  }
  const markRef = useRef(markDisputes)
  useLayoutEffect(() => {
    markRef.current = markDisputes
  })

  useEffect(() => {
    const m = new BpmnModeler({ container: container.current!, ...THEME }) // keyboard binds to the canvas
    modeler.current = m
    m.on("selection.changed", (e: { newSelection: DiagramElement[] }) =>
      latest.current.onSelect(e.newSelection.length === 1 ? e.newSelection[0].id : null),
    )
    m.on("commandStack.changed", () => latest.current.onChange())
    // Keep the diagram's size in step with its container (window or panel resizes).
    const observer = new ResizeObserver(() => (m.get("canvas") as CanvasService).resized())
    observer.observe(container.current!)
    return () => {
      observer.disconnect()
      m.destroy()
      modeler.current = null
      imported.current = false
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const keepView = imported.current ? svc("canvas").viewbox() : null
    void fontReady.then(() => {
      const m = modeler.current
      if (!m || cancelled) return
      m.importXML(xml)
        .then(({ warnings }) => {
          if (cancelled) return
          if (warnings.length) console.warn("bpmn-js import warnings", warnings)
          if (keepView) svc("canvas").viewbox(keepView)
          else svc("canvas").zoom("fit-viewport")
          imported.current = true
          markRef.current()
        })
        .catch((e: Error) => !cancelled && latest.current.onImportError(e.message))
    })
    return () => {
      cancelled = true
    }
  }, [xml])

  // Re-mark when the set of disputed steps changes (a point was settled, a meeting merged).
  const disputeKey = (disputes ?? []).map((d) => `${d.nodeId}:${d.label}`).join("|")
  useEffect(() => markRef.current(), [disputeKey])

  useImperativeHandle(ref, () => ({
    async saveXML() {
      const { xml: out } = await modeler.current!.saveXML({ format: true })
      if (!out) throw new Error("The diagram could not be serialized")
      return out
    },
    select(xmlId: string) {
      const el = svc("elementRegistry").get(xmlId)
      if (!el) return false
      svc("selection").select(el)
      svc("canvas").scrollToElement(el)
      return true
    },
    zoomToFit() {
      svc("canvas").zoom("fit-viewport")
    },
  }))

  return (
    <div
      ref={container}
      className="bpmn-canvas h-full w-full"
      role="application"
      aria-label="BPMN diagram editor. Use the palette on the left to add elements."
    />
  )
})
