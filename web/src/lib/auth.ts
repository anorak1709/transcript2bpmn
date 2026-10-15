import { useSyncExternalStore } from "react"

import { getApiKey } from "@/lib/api"

function subscribe(onChange: () => void): () => void {
  window.addEventListener("t2b:auth", onChange)
  window.addEventListener("storage", onChange) // signed in/out in another tab
  return () => {
    window.removeEventListener("t2b:auth", onChange)
    window.removeEventListener("storage", onChange)
  }
}

/** The stored API key; re-renders when it changes (sign in, sign out, 401 anywhere). */
export function useApiKey(): string | null {
  return useSyncExternalStore(subscribe, getApiKey, () => null)
}
