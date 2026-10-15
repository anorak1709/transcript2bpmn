import "bpmn-js/dist/assets/diagram-js.css"
import "bpmn-js/dist/assets/bpmn-js.css"
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css" // font files, not data: URLs (CSP)

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
  scrollToElement(element: DiagramElement): void
}
interface Services {
  canvas: CanvasService
  elementRegistry: { get(id: string): DiagramElement | undefined }
  selection: { select(element: DiagramElement): void }
}

export interface BpmnCanvasHandle {
  saveXML(): Promise<string>
  select(xmlId: string): boolean
  zoomToFit(): void
}

export const BpmnCanvas = forwardRef<
  BpmnCanvasHandle,
  {
    xml: string
    onSelect: (xmlId: string | null) => void
    onChange: () => void
    onImportError: (message: string) => void
  }
>(function BpmnCanvas({ xml, onSelect, onChange, onImportError }, ref) {
  const container = useRef<HTMLDivElement>(null)
  const modeler = useRef<BpmnModeler | null>(null)
  const callbacks = useRef({ onSelect, onChange, onImportError })
  useLayoutEffect(() => {
    callbacks.current = { onSelect, onChange, onImportError } // latest handlers for bpmn-js events
  })
  const imported = useRef(false)

  const svc = <K extends keyof Services>(name: K): Services[K] => modeler.current!.get(name) as Services[K]

  useEffect(() => {
    const m = new BpmnModeler({ container: container.current! }) // keyboard shortcuts bind to the canvas itself
    modeler.current = m
    m.on("selection.changed", (e: { newSelection: DiagramElement[] }) =>
      callbacks.current.onSelect(e.newSelection.length === 1 ? e.newSelection[0].id : null),
    )
    m.on("commandStack.changed", () => callbacks.current.onChange())
    return () => {
      m.destroy()
      modeler.current = null
      imported.current = false
    }
  }, [])

  useEffect(() => {
    const m = modeler.current
    if (!m) return
    let cancelled = false
    const keepView = imported.current ? svc("canvas").viewbox() : null
    m.importXML(xml)
      .then(({ warnings }) => {
        if (cancelled) return
        if (warnings.length) console.warn("bpmn-js import warnings", warnings)
        if (keepView) svc("canvas").viewbox(keepView)
        else svc("canvas").zoom("fit-viewport")
        imported.current = true
      })
      .catch((e: Error) => !cancelled && callbacks.current.onImportError(e.message))
    return () => {
      cancelled = true
    }
  }, [xml])

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
      className="bpmn-canvas h-full w-full bg-white text-neutral-900"
      role="application"
      aria-label="BPMN diagram editor. Use the palette on the left to add elements."
    />
  )
})
