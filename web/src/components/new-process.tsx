import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { useNavigate } from "react-router"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"

/** Create a process: a name, and optionally how long meeting content is kept. */
export function NewProcessDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState("")
  const [retention, setRetention] = useState("")
  const create = useMutation({
    mutationFn: () => api.createProject(name.trim(), retention ? Number(retention) : null),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] })
      onOpenChange(false)
      setName("")
      setRetention("")
      navigate(`/projects/${p.id}?tab=sources`)
    },
    onError: (e) => toast.error(e.message),
  })
  const retentionInvalid = retention !== "" && !(Number.isInteger(Number(retention)) && Number(retention) >= 1)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim() && !retentionInvalid) create.mutate()
          }}
          className="space-y-5"
        >
          <DialogHeader>
            <DialogTitle>New process</DialogTitle>
            <DialogDescription>One per process. Every meeting about it is merged into a single map.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <label htmlFor="project-name" className="eyebrow block">
              Process name
            </label>
            <Input
              id="project-name"
              placeholder="e.g. Supplier invoice approval"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={255}
              required
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="project-retention" className="eyebrow block">
              Delete meeting content after
            </label>
            <div className="flex items-center gap-2">
              <Input
                id="project-retention"
                inputMode="numeric"
                placeholder="Keep"
                className="tabular w-28"
                value={retention}
                onChange={(e) => setRetention(e.target.value.replace(/[^\d]/g, ""))}
                aria-invalid={retentionInvalid}
                aria-describedby="retention-help"
              />
              <span className="text-sm text-fg-muted">days</span>
            </div>
            <p id="retention-help" className="text-xs text-fg-muted">
              Recordings and transcript text are deleted after this many days. Maps are kept.
            </p>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || retentionInvalid || create.isPending}>
              {create.isPending ? "Creating…" : "Create process"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
