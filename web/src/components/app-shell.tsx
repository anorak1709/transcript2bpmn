import { useQuery } from "@tanstack/react-query"
import { Inbox, KeyRound, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Plus, Settings, Workflow } from "lucide-react"
import { useState } from "react"
import { NavLink, Outlet, useLocation } from "react-router"

import { NewProcessDialog } from "@/components/new-process"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { api, setApiKey } from "@/lib/api"
import { cn } from "@/lib/utils"

const COLLAPSE_KEY = "t2b_sidebar_collapsed"

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1"
  } catch {
    return false
  }
}

function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase() ?? "")
      .join("") || "?"
  )
}

function Count({ n, label }: { n: number; label: string }) {
  if (!n) return null
  return (
    <span
      className="tabular ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-warn-tint px-1.5 text-xs font-semibold text-warn"
      aria-label={`${n} ${label}`}
    >
      {n}
    </span>
  )
}

const item = (active: boolean, collapsed: boolean) =>
  cn(
    "transition-quiet flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm",
    collapsed && "justify-center px-0",
    active ? "bg-raised font-medium text-fg" : "text-fg-muted hover:bg-raised hover:text-fg",
  )

/** Sidebar: inbox, every process with its open-item count, settings, account. */
function SidebarBody({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const [creating, setCreating] = useState(false)
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, refetchInterval: 15_000 })
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: api.inbox, refetchInterval: 15_000 })
  const waiting = (inbox.data ?? []).filter((i) => i.kind !== "gap").length

  return (
    <div className="flex h-full flex-col p-3">
      <div className={cn("mb-4 flex h-9 items-center gap-2.5 px-1", collapsed && "justify-center px-0")}>
        <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-md bg-brand text-on-brand">
          <Workflow className="size-4" strokeWidth={2.25} aria-hidden />
        </span>
        {!collapsed && <span className="truncate text-sm font-semibold">Transcript to BPMN</span>}
      </div>

      <NavLink to="/" end onClick={onNavigate} className={({ isActive }) => item(isActive, collapsed)} title="Inbox">
        <Inbox className="size-4 shrink-0" aria-hidden />
        {collapsed ? <span className="sr-only">Inbox</span> : <span>Inbox</span>}
        {!collapsed && <Count n={waiting} label="items waiting" />}
      </NavLink>

      <div className={cn("mt-5 mb-1 flex h-7 items-center justify-between pl-2.5", collapsed && "justify-center pl-0")}>
        {!collapsed && <span className="eyebrow">Processes</span>}
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="New process"
          title="New process"
          onClick={() => setCreating(true)}
        >
          <Plus aria-hidden />
        </Button>
      </div>
      <nav aria-label="Processes" className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1">
        <ul className="space-y-0.5">
          {(projects.data ?? []).map((p) => {
            const open = p.open_conflicts + p.open_policy_differences
            return (
              <li key={p.id}>
                <NavLink
                  to={`/projects/${p.id}`}
                  onClick={onNavigate}
                  title={p.name}
                  className={({ isActive }) => item(isActive, collapsed)}
                >
                  {collapsed ? (
                    <span className="relative inline-flex size-7 items-center justify-center rounded-md bg-raised text-xs font-semibold">
                      {initials(p.name)}
                      {open > 0 && (
                        <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-warn" aria-hidden />
                      )}
                      <span className="sr-only">{p.name}</span>
                    </span>
                  ) : (
                    <>
                      <span className="min-w-0 flex-1 truncate">{p.name}</span>
                      <Count n={open} label="open items" />
                    </>
                  )}
                </NavLink>
              </li>
            )
          })}
        </ul>
        {projects.data?.length === 0 && !collapsed && (
          <p className="px-2.5 py-2 text-xs text-fg-muted">No processes yet. Use + to create one.</p>
        )}
      </nav>

      <div className="mt-2 space-y-0.5 border-t border-line pt-2">
        <NavLink
          to="/settings"
          onClick={onNavigate}
          className={({ isActive }) => item(isActive, collapsed)}
          title="Settings"
        >
          <Settings className="size-4 shrink-0" aria-hidden />
          {collapsed ? <span className="sr-only">Settings</span> : <span>Settings</span>}
        </NavLink>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" className={cn(item(false, collapsed), "w-full")} title="Account">
              <KeyRound className="size-4 shrink-0" aria-hidden />
              {collapsed ? <span className="sr-only">Account</span> : <span>Signed in</span>}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start">
            <DropdownMenuLabel className="font-normal text-fg-muted">Signed in with an API key</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => setApiKey(null)}>
              <LogOut aria-hidden /> Sign out of this browser
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <NewProcessDialog open={creating} onOpenChange={setCreating} />
    </div>
  )
}

/** App frame: collapsible sidebar on large screens, a drawer on small ones. */
export function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [drawer, setDrawer] = useState(false)
  const editor = useLocation().pathname.startsWith("/maps/") // the editor uses the whole height
  const toggle = () =>
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1")
      } catch {
        /* a per-browser convenience only */
      }
      return !c
    })

  return (
    <div className="flex min-h-svh bg-app">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-4 focus:z-50 focus:rounded-md focus:bg-raised focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <aside
        className={cn(
          "transition-quiet sticky top-0 hidden h-svh shrink-0 border-r border-line bg-panel lg:block",
          collapsed ? "w-16" : "w-64",
        )}
      >
        <SidebarBody collapsed={collapsed} />
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="absolute top-4 -right-3.5 z-10 size-7 rounded-full border border-line bg-panel"
        >
          {collapsed ? <PanelLeftOpen aria-hidden /> : <PanelLeftClose aria-hidden />}
        </Button>
      </aside>

      <Sheet open={drawer} onOpenChange={setDrawer}>
        <SheetContent side="left" className="w-72 bg-panel p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SidebarBody collapsed={false} onNavigate={() => setDrawer(false)} />
        </SheetContent>
      </Sheet>

      <div className={cn("flex min-w-0 flex-1 flex-col", editor && "h-svh")}>
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-3 lg:hidden">
          <Button variant="ghost" size="icon" aria-label="Open navigation" onClick={() => setDrawer(true)}>
            <Menu aria-hidden />
          </Button>
          <span className="text-sm font-semibold">Transcript to BPMN</span>
        </div>
        <main id="main" className={cn("min-w-0 flex-1", editor && "flex min-h-0 flex-col")}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}

/** Content page: 1200px measure, comfortable padding. */
export function Page({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("mx-auto w-full max-w-[1200px] px-4 py-6 sm:px-8 sm:py-8", className)}>{children}</div>
}
