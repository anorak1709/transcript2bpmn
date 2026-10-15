import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Built into the Python package so FastAPI serves it at /app (same origin: strict CSP holds).
const API = process.env.API_URL ?? "http://localhost:8000"
const apiPaths = ["/projects", "/transcripts", "/jobs", "/maps", "/conflicts", "/keys", "/usage", "/audit", "/health"]

export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  // assetsInlineLimit 0: never inline files as data: URLs (the CSP only allows same-origin fonts).
  build: { outDir: "../app/static/app", emptyOutDir: true, chunkSizeWarningLimit: 1500, assetsInlineLimit: 0 },
  server: { proxy: Object.fromEntries(apiPaths.map((p) => [p, API])) },
})
