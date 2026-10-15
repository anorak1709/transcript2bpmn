import { KeyRound, Loader2, Workflow } from "lucide-react"
import { useState } from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { setApiKey, verifyKey } from "@/lib/api"

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
    <main className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Workflow className="size-5 text-foreground" aria-hidden />
            Transcript to BPMN
          </div>
          <CardTitle asChild className="text-2xl">
            <h1>Sign in with an API key</h1>
          </CardTitle>
          <CardDescription>Your workspace admin issues keys. The key is stored only in this browser.</CardDescription>
        </CardHeader>
        <form onSubmit={submit} noValidate>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="api-key">API key</Label>
              <Input
                id="api-key"
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder="t2b_…"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                aria-invalid={!!error}
                aria-describedby={error ? "api-key-error" : undefined}
                autoFocus
              />
            </div>
            {error && (
              <Alert variant="destructive" id="api-key-error">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </CardContent>
          <CardFooter className="pt-6">
            <Button type="submit" className="w-full" disabled={checking || !key.trim()}>
              {checking ? <Loader2 className="animate-spin" aria-hidden /> : <KeyRound aria-hidden />}
              {checking ? "Checking key…" : "Continue"}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </main>
  )
}
