import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, KeyRound, LogOut } from "lucide-react"
import { NavLink, Outlet } from "react-router"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { api, setApiKey } from "@/lib/api"
import { cn } from "@/lib/utils"

const NAV = [
  { to: "/projects", label: "Processes" },
  { to: "/settings", label: "Settings" },
]

/** Top bar (MASTER): wordmark, two sections, account. */
export function AppShell() {
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60_000 })
  return (
    <div className="flex min-h-svh flex-col bg-bg">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-4 focus:z-50 focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="border-b-2 border-fg bg-bg">
        <div className="mx-auto flex h-14 max-w-[1120px] items-center gap-2 px-4 sm:gap-8 sm:px-6">
          <NavLink
            to="/projects"
            className="macro inline-flex min-h-9 shrink-0 items-center text-[1rem] leading-none tracking-[-0.03em] sm:text-[1.2rem]"
          >
            <span className="sm:hidden" aria-hidden>
              T2B
            </span>
            <span className="sr-only sm:hidden">Transcript to BPMN</span>
            <span className="hidden sm:inline">
              Transcript
              <span className="text-hazard" aria-hidden>
                →
              </span>
              <span className="sr-only"> to </span>BPMN
              <sup className="ml-0.5 font-mono text-[0.6rem] tracking-normal" aria-hidden>
                ®
              </sup>
            </span>
          </NavLink>
          <nav aria-label="Main" className="flex items-center gap-0 sm:gap-1">
            {NAV.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    "transition-quiet inline-flex h-9 items-center px-2 font-mono text-[0.78rem] font-semibold tracking-[0.08em] uppercase sm:px-3",
                    isActive ? "bg-fg text-bg" : "text-fg-muted hover:bg-surface hover:text-fg",
                  )
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="normal-case tracking-normal text-fg-muted"
                  aria-label="Signed in: account menu"
                >
                  <KeyRound aria-hidden />{" "}
                  <span className="hidden max-w-48 truncate sm:inline">{me.data?.email ?? "Signed in"}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-64">
                <DropdownMenuLabel className="font-normal text-fg-muted">
                  {me.data?.email ? `Signed in as ${me.data.email}` : "Signed in with an API key"}
                  {me.data && <span className="block text-fg">{me.data.workspace.name}</span>}
                </DropdownMenuLabel>
                {(me.data?.workspaces.length ?? 0) > 1 && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuLabel className="label font-normal">Switch workspace</DropdownMenuLabel>
                    {me.data!.workspaces.map((w) => (
                      <DropdownMenuItem
                        key={w.id}
                        disabled={w.id === me.data!.workspace.id}
                        onSelect={() =>
                          api.switchWorkspace(w.id).then(
                            (s) => {
                              qc.clear()
                              setApiKey(s.key)
                            },
                            (e: Error) => toast.error(e.message),
                          )
                        }
                      >
                        {w.id === me.data!.workspace.id ? <Check aria-hidden /> : <span className="size-4" />} {w.name}
                      </DropdownMenuItem>
                    ))}
                  </>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={() => {
                    // End the session on the server too (an integration key stays valid).
                    void api
                      .logout()
                      .catch(() => undefined)
                      .finally(() => setApiKey(null))
                  }}
                >
                  <LogOut aria-hidden /> Sign out of this browser
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>
      {me.data?.sandbox && (
        <p role="status" className="bg-fg px-6 py-2 text-center font-mono text-[0.78rem] tracking-[0.04em] text-bg">
          You're in a demo sandbox: explore, settle points, edit and export. AI processing is switched off, and this
          copy is deleted within a day.
        </p>
      )}
      <main id="main" className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}

/** Document page: 1120px measure with generous margins (MASTER: compact tables in airy pages). */
export function Page({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("mx-auto w-full max-w-[1120px] px-4 pt-10 pb-20 sm:px-8 sm:pt-14", className)}>
      {children}
      <footer className="mt-24 flex items-center gap-4 border-t-2 border-fg pt-3" aria-hidden>
        <div className="barcode w-28 shrink-0" />
        <span className="label truncate text-fg-subtle">BPMN 2.0 /// Camunda · Signavio · Word · PDF</span>
        <span className="label ml-auto shrink-0 text-fg-subtle">T2B®</span>
      </footer>
    </div>
  )
}
