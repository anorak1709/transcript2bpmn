import "./index.css"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { lazy, StrictMode, Suspense } from "react"
import { createRoot } from "react-dom/client"
import { createBrowserRouter, Link, Navigate, RouterProvider } from "react-router"

import { AppShell, Page } from "@/components/app-shell"
import { PageHeader } from "@/components/dossier"
import { Skeleton } from "@/components/ui/skeleton"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ApiError } from "@/lib/api"
import { useApiKey } from "@/lib/auth"
import { ProjectPage } from "@/pages/project"
import { ReviewPage } from "@/pages/review"
import { Projects } from "@/pages/projects"
import { Settings } from "@/pages/settings"
import { AuthCallback, SignIn } from "@/pages/sign-in"

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
const LivePage = lazy(() => import("@/pages/live").then((m) => ({ default: m.LivePage })))

function NotFound() {
  return (
    <Page>
      <PageHeader eyebrow="Not found" title="No such page" />
      <Link to="/projects" className="underline">
        Back to the index of processes
      </Link>
    </Page>
  )
}

function RequireKey() {
  return useApiKey() ? <AppShell /> : <SignIn />
}

const router = createBrowserRouter(
  [
    // A stakeholder's sign-off link: no API key, no app shell (the token is the credential).
    { path: "review/:token", element: <ReviewPage /> },
    { path: "auth", element: <AuthCallback /> }, // a magic link lands here
    {
      element: <RequireKey />,
      children: [
        { index: true, element: <Navigate to="/projects" replace /> },
        { path: "projects", element: <Projects /> },
        { path: "projects/:projectId", element: <ProjectPage /> },
        {
          path: "projects/:projectId/live",
          element: (
            <Suspense fallback={<Skeleton className="m-6 h-[70svh] rounded-sm bg-paper-shade" />}>
              <LivePage />
            </Suspense>
          ),
        },
        {
          path: "maps/:mapId",
          element: (
            <Suspense fallback={<Skeleton className="m-6 h-[70svh] rounded-sm bg-paper-shade" />}>
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
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <RouterProvider router={router} />
        <Toaster closeButton position="bottom-left" />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
