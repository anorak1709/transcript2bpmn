import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { setApiKey, verifyKey } from "@/lib/api"

/** A dossier title page: the product name set large, one field, one action. */
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
    <main className="flex min-h-svh flex-col bg-paper">
      <div className="mx-auto flex w-full max-w-[560px] flex-1 flex-col justify-center px-6 py-16">
        <p className="label mb-6">A process mapping workspace</p>
        <h1 className="text-[3.5rem] leading-[1.02] tracking-[-0.015em]">
          Transcript <span className="text-graphite italic">to</span> BPMN
        </h1>
        <p className="serif measure mt-4 text-xl leading-snug text-graphite italic">
          Meetings, set down as process maps: every step traced to the words that described it.
        </p>
        <hr className="my-10 border-rule" />
        <form onSubmit={submit} noValidate className="space-y-3">
          <label htmlFor="api-key" className="label block">
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
            className="font-mono text-sm"
            autoFocus
          />
          {error ? (
            <p id="api-key-error" role="alert" className="text-sm text-oxblood">
              {error}
            </p>
          ) : (
            <p id="api-key-help" className="text-sm text-graphite">
              Issued by your workspace admin. Kept only in this browser.
            </p>
          )}
          <div className="pt-3">
            <Button type="submit" disabled={checking || !key.trim()}>
              {checking ? "Checking key…" : "Open the workspace"}
            </Button>
          </div>
        </form>
      </div>
      <footer className="smallcaps border-t border-hairline px-6 py-4 text-center text-xs text-graphite">
        BPMN 2.0 · exports for Camunda and Signavio
      </footer>
    </main>
  )
}
