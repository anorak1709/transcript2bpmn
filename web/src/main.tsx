import "./index.css"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ThemeProvider } from "next-themes"
import { lazy, StrictMode, Suspense } from "react"
import { createRoot } from "react-dom/client"
import { createBrowserRouter, Link, Navigate, RouterProvider } from "react-router"

import { AppShell, Page } from "@/components/app-shell"
import { Skeleton } from "@/components/ui/skeleton"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ApiError } from "@/lib/api"
import { useApiKey } from "@/lib/auth"
import { ProjectPage } from "@/pages/project"
import { Projects } from "@/pages/projects"
import { Settings } from "@/pages/settings"
import { SignIn } from "@/pages/sign-in"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      // 4xx won't fix themselves; retry only network / server hiccups.
      retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
    },
  },
})

// The editor pulls in bpmn-js (most of the JS); load it only when a map is opened.
const MapEditor = lazy(() => import("@/pages/map-editor").then((m) => ({ default: m.MapEditor })))

function NotFound() {
  return (
    <Page title="Page not found">
      <Link to="/projects" className="text-sm underline">
        Go to projects
      </Link>
    </Page>
  )
}

function RequireKey() {
  return useApiKey() ? <AppShell /> : <SignIn />
}

const router = createBrowserRouter(
  [
    {
      element: <RequireKey />,
      children: [
        { index: true, element: <Navigate to="/projects" replace /> },
        { path: "projects", element: <Projects /> },
        { path: "projects/:projectId", element: <ProjectPage /> },
        {
          path: "maps/:mapId",
          element: (
            <Suspense fallback={<Skeleton className="m-4 h-[70svh] rounded-xl" />}>
              <MapEditor />
            </Suspense>
          ),
        },
        { path: "settings", element: <Settings /> },
        { path: "*", element: <NotFound /> },
      ],
    },
  ],
  { basename: "/app" },
)

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={300}>
          <RouterProvider router={router} />
          <Toaster richColors closeButton position="bottom-left" />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
