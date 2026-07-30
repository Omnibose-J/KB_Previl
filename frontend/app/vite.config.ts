import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { defineConfig, type Plugin, type ResolvedConfig } from "vite";
import react from "@vitejs/plugin-react";

const require = createRequire(import.meta.url);

/**
 * MapLibre v6 builds its worker URL at RUNTIME, relative to the loaded bundle:
 *
 *   let t = e.endsWith("-dev.mjs") ? "maplibre-gl-worker-dev.mjs" : "maplibre-gl-worker.mjs";
 *   return new URL(`./${t}`, e).href
 *
 * Rollup cannot see that string, so it never emits the file and the built app
 * requests `/assets/maplibre-gl-worker.mjs` and gets a 404. The failure is
 * quiet in the worst way: raster tiles keep rendering on the main thread, so
 * the map LOOKS fine while every GeoJSON layer — the grade cells, the whole
 * point of the screen — stays empty.
 *
 * `optimizeDeps.exclude` below fixes the same class of bug in dev. It does
 * nothing for `vite build`, which is why this went unnoticed until the built
 * app became the demo path (service/app.py mounts dist/).
 */
function emitMapLibreWorker(): Plugin {
  let config: ResolvedConfig;
  return {
    name: "emit-maplibre-worker",
    apply: "build",
    configResolved(resolved) {
      config = resolved;
    },
    generateBundle() {
      // The worker is not one file: it does `import ... from
      // "./maplibre-gl-shared.mjs"`. Copying only the entry produced a worker
      // that fetched with 200 and then died on construction — the map looked
      // identical to the missing-file case. So follow the relative imports and
      // emit every file the graph reaches; a future MapLibre that splits the
      // chunk further keeps working instead of failing the same quiet way.
      const seen = new Set<string>();
      const queue = [require.resolve("maplibre-gl/dist/maplibre-gl-worker.mjs")];
      const rel = /from\s*["'](\.\/[^"']+)["']/g;

      while (queue.length) {
        const file = queue.pop()!;
        const name = file.replace(/\\/g, "/").split("/").pop()!;
        if (seen.has(name)) continue;
        seen.add(name);

        const source = readFileSync(file);
        this.emitFile({
          type: "asset",
          // Next to the bundle, because that is what the runtime URL resolves
          // against — and what the worker's own relative imports resolve
          // against too. Not a hardcoded "assets/": assetsDir is configurable
          // and a fixed path would break silently in exactly this way.
          fileName: `${config.build.assetsDir}/${name}`,
          source,
        });

        const dir = file.slice(0, file.length - name.length);
        for (const [, spec] of source.toString().matchAll(rel)) {
          queue.push(dir + spec.slice(2));
        }
      }
    },
  };
}

// Proxy keeps the no-mock rule practical: the dev server always talks to the
// real FastAPI backend (service/app.py, port 8000). If the backend is down,
// requests fail loudly - do NOT add a mock fallback here.
export default defineConfig({
  plugins: [react(), emitMapLibreWorker()],
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
