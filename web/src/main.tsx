import "./index.css"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { lazy, StrictMode, Suspense } from "react"
import { createRoot } from "react-dom/client"
import { createBrowserRouter, Link, Navigate, RouterProvider } from "react-router"

import { AppShell, Page } from "@/components/app-shell"
import { PageHeader } from "@/components/kit"
import { Skeleton } from "@/components/ui/skeleton"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ApiError } from "@/lib/api"
import { useApiKey } from "@/lib/auth"
import { ProjectPage } from "@/pages/project"
import { ReviewPage } from "@/pages/review"
import { InboxPage } from "@/pages/inbox"
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
    <Page>
      <PageHeader title="No such page" />
      <Link to="/" className="text-brand underline-offset-4 hover:underline">
        Back to the inbox
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
    {
      element: <RequireKey />,
      children: [
        { index: true, element: <InboxPage /> },
        { path: "projects", element: <Navigate to="/" replace /> }, // the sidebar is the index now
        { path: "projects/:projectId", element: <ProjectPage /> },
        {
          path: "maps/:mapId",
          element: (
            <Suspense fallback={<Skeleton className="m-6 h-[70svh] rounded-lg bg-panel" />}>
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
