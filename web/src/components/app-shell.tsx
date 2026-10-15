import { KeyRound, LogOut } from "lucide-react"
import { NavLink, Outlet } from "react-router"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { setApiKey } from "@/lib/api"
import { cn } from "@/lib/utils"

const NAV = [
  { to: "/projects", label: "Projects" },
  { to: "/settings", label: "Settings" },
]

/** Masthead (MASTER: top bar): serif wordmark, small-caps sections, hairline beneath. */
export function AppShell() {
  return (
    <div className="flex min-h-svh flex-col bg-paper">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-4 focus:z-50 focus:bg-sheet focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="border-b border-rule bg-paper">
        <div className="mx-auto flex h-14 max-w-[1120px] items-center gap-3 px-4 sm:gap-8 sm:px-6">
          <NavLink
            to="/projects"
            className="serif inline-flex min-h-9 shrink-0 items-center text-[1.15rem] leading-none font-[560] tracking-[-0.01em] sm:text-[1.35rem]"
          >
            Transcript <span className="text-graphite italic">to</span> BPMN
          </NavLink>
          <nav aria-label="Main" className="flex items-center gap-0 sm:gap-1">
            {NAV.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    "smallcaps transition-quiet inline-flex h-9 items-center border-b-2 px-2 text-[0.95rem] font-bold",
                    isActive ? "border-ink text-ink" : "border-transparent text-graphite hover:text-ink",
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
                  className="smallcaps text-graphite"
                  aria-label="Signed in: account menu"
                >
                  <KeyRound aria-hidden /> <span className="hidden sm:inline">Signed in</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel className="font-normal text-graphite">Signed in with an API key</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => setApiKey(null)}>
                  <LogOut aria-hidden /> Sign out of this browser
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>
      <main id="main" className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}

/** Document page: 1120px measure with generous margins (MASTER: compact tables in airy pages). */
export function Page({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("mx-auto w-full max-w-[1120px] px-4 pt-10 pb-20 sm:px-6 sm:pt-12", className)}>{children}</div>
  )
}
