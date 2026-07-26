import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy keeps the no-mock rule practical: the dev server always talks to the
// real FastAPI backend (service/app.py, port 8000). If the backend is down,
// requests fail loudly - do NOT add a mock fallback here.
export default defineConfig({
  plugins: [react()],
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
