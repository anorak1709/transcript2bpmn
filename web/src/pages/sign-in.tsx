import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { auth, setApiKey, verifyKey } from "@/lib/api"

function Title() {
  return (
    <div className="mb-12">
      <div className="label xmarks mb-8 flex justify-between border-y-2 border-fg py-1.5">
        <span>/// Process mapping workspace</span>
        <span className="text-fg-subtle">T2B® · BPMN 2.0</span>
      </div>
      <h1 className="macro text-[clamp(3rem,9vw,5.5rem)]">
        Transcript
        <span className="text-hazard" aria-hidden>
          →
        </span>
        <span className="sr-only"> to </span>
        <br />
        BPMN
      </h1>
      <p className="measure mt-6 text-xl leading-snug text-fg-muted">
        Turn process interviews into BPMN maps. Every step links back to the words that described it.
      </p>
    </div>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-svh flex-col bg-bg">
      <div className="mx-auto flex w-full max-w-[600px] flex-1 flex-col justify-center px-6 py-16">
        <Title />
        {children}
      </div>
      <footer className="flex items-center gap-4 border-t-2 border-fg px-6 py-3">
        <div className="barcode w-24 shrink-0" aria-hidden />
        <span className="label truncate">BPMN 2.0 · exports for Camunda and Signavio</span>
      </footer>
    </main>
  )
}

/** Title page: sign in by email (magic link), with an API key, or try the demo. */
export function SignIn() {
  const [mode, setMode] = useState<"email" | "key">("email")
  const [email, setEmail] = useState("")
  const [key, setKey] = useState("")
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [settingUp, setSettingUp] = useState(false)
  const demo = useQuery({ queryKey: ["demo-status"], queryFn: auth.demoStatus, retry: false })

  async function sendLink(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await auth.requestLink(email.trim())
      setSentTo(email.trim())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function useKey(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = key.trim()
    if (!trimmed.startsWith("t2b_")) {
      setError("API keys start with t2b_. Ask your workspace admin for one.")
      return
    }
    setBusy(true)
    setError(null)
    try {
      // Verify first, store second: storing switches the app to its signed-in view.
      if (await verifyKey(trimmed)) setApiKey(trimmed)
      else setError("That key isn't valid or was revoked.")
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function tryDemo() {
    setSettingUp(true)
    setError(null)
    try {
      setApiKey((await auth.sandbox()).key)
    } catch (err) {
      setError((err as Error).message)
      setSettingUp(false)
    }
  }

  const errorLine = error && (
    <p id="sign-in-error" role="alert" className="text-sm text-signal">
      {error}
    </p>
  )

  return (
    <Shell>
      {demo.data?.sandboxes && (
        <div className="mb-10">
          <Button onClick={() => void tryDemo()} disabled={settingUp}>
            {settingUp ? "Setting up your demo…" : "Try the demo"}
          </Button>
          <p className="mt-2 text-sm text-fg-muted">
            Your own copy of two sample processes, with no sign-up. AI is switched off; it's deleted after{" "}
            {demo.data.sandbox_hours} hours.
          </p>
        </div>
      )}

      {sentTo ? (
        <div role="status" className="space-y-2">
          <p className="text-xl">Check your email</p>
          <p className="text-fg-muted">
            We sent a sign-in link to <span className="text-fg">{sentTo}</span>. It works once and expires in 15
            minutes.
          </p>
          <button type="button" className="text-sm text-fg-muted underline" onClick={() => setSentTo(null)}>
            Use a different address
          </button>
        </div>
      ) : mode === "email" ? (
        <form onSubmit={sendLink} noValidate className="space-y-3">
          <label htmlFor="email" className="label block">
            Work email
          </label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={!!error}
            aria-describedby={error ? "sign-in-error" : "email-help"}
            autoFocus
          />
          {errorLine || (
            <p id="email-help" className="text-sm text-fg-muted">
              We'll email you a sign-in link. New here? The link creates your workspace.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-4 pt-3">
            <Button
              type="submit"
              variant={demo.data?.sandboxes ? "outline" : "default"}
              disabled={busy || !email.trim()}
            >
              {busy ? "Sending…" : "Email me a sign-in link"}
            </Button>
            <button type="button" className="text-sm text-fg-muted underline" onClick={() => setMode("key")}>
              Use an API key instead
            </button>
          </div>
        </form>
      ) : (
        <form onSubmit={useKey} noValidate className="space-y-3">
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
            aria-describedby={error ? "sign-in-error" : "api-key-help"}
            className="font-mono text-sm"
            autoFocus
          />
          {errorLine || (
            <p id="api-key-help" className="text-sm text-fg-muted">
              For integrations and admins. Kept only in this browser.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-4 pt-3">
            <Button type="submit" disabled={busy || !key.trim()}>
              {busy ? "Checking key…" : "Open the workspace"}
            </Button>
            <button type="button" className="text-sm text-fg-muted underline" onClick={() => setMode("email")}>
              Sign in with email instead
            </button>
          </div>
        </form>
      )}
    </Shell>
  )
}

/** Landing page of a magic link (/app/auth?token=…): exchange it for a session. */
export function AuthCallback() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get("token")
  const [error, setError] = useState<string | null>(token ? null : "This link is missing its token.")
  const started = useRef(false)
  useEffect(() => {
    if (started.current || !token) return // a token works once: never send it twice (StrictMode)
    started.current = true
    auth.verify(token).then(
      (s) => {
        setApiKey(s.key)
        navigate("/projects", { replace: true })
      },
      (e: Error) => setError(e.message),
    )
  }, [token, navigate])
  return (
    <Shell>
      {error ? (
        <div className="space-y-3">
          <p role="alert" className="text-signal">
            {error}
          </p>
          <Button variant="outline" onClick={() => navigate("/", { replace: true })}>
            Back to sign in
          </Button>
        </div>
      ) : (
        <p className="text-fg-muted">Signing you in…</p>
      )}
    </Shell>
  )
}
