import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy keeps the no-mock rule practical: the dev server always talks to the
// real FastAPI backend (service/app.py, port 8000). If the backend is down,
// requests fail loudly - do NOT add a mock fallback here.
export default defineConfig({
  plugins: [react()],
  // MapLibre spawns its GeoJSON parser in a Web Worker via `new Worker(new
  // URL(...))`. esbuild's dep pre-bundling rewrites that URL and the worker
  // dies silently: raster tiles still render (main thread) but every
  // vector/GeoJSON layer stays empty with no console error. Excluding it keeps
  // the worker resolvable in dev.
  optimizeDeps: { exclude: ["maplibre-gl"] },
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
    fs: {
      // allow importing ../design/tokens/tokens.css (single source of truth)
      allow: [".."],
    },
  },
});
