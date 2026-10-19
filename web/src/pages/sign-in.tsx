import { Workflow } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { setApiKey, verifyKey } from "@/lib/api"

/** Sign-in: one field, one action. */
export function SignIn() {
  const [key, setKey] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = key.trim()
    if (!trimmed.startsWith("t2b_")) {
      setError("API keys start with t2b_. Ask your workspace admin for one.")
      return
    }
    setChecking(true)
    setError(null)
    try {
      // Verify first, store second: storing switches the app to its signed-in view.
      if (await verifyKey(trimmed)) setApiKey(trimmed)
      else setError("That key isn't valid or was revoked.")
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setChecking(false)
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-app px-4 py-12">
      <div className="w-full max-w-[400px]">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="inline-flex size-8 items-center justify-center rounded-md bg-brand text-on-brand">
            <Workflow className="size-4.5" strokeWidth={2.25} aria-hidden />
          </span>
          <span className="text-sm font-semibold">Transcript to BPMN</span>
        </div>
        <div className="rounded-lg border border-line bg-panel p-6">
          <h1 className="text-xl">Sign in</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Turn meetings into process maps, with every step traced to what was said.
          </p>
          <form onSubmit={submit} noValidate className="mt-6 space-y-2">
            <label htmlFor="api-key" className="eyebrow block">
              API key
            </label>
            <Input
              id="api-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="t2b_…"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              aria-invalid={!!error}
              aria-describedby={error ? "api-key-error" : "api-key-help"}
              className="font-mono"
              autoFocus
            />
            {error ? (
              <p id="api-key-error" role="alert" className="text-sm text-bad">
                {error}
              </p>
            ) : (
              <p id="api-key-help" className="text-xs text-fg-muted">
                Issued by your workspace admin. Kept only in this browser.
              </p>
            )}
            <Button type="submit" className="mt-4 w-full" disabled={checking || !key.trim()}>
              {checking ? "Checking key…" : "Open the workspace"}
            </Button>
          </form>
        </div>
        <p className="mt-4 text-center text-xs text-fg-subtle">BPMN 2.0 · exports for Camunda and Signavio</p>
      </div>
    </main>
  )
}
