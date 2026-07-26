import type { EconomicsInput, EconomicsResult, GridCell, GridDetail, Meta } from "./types";

// Single trust boundary for all server data. No-mock rule (ui-spec §1):
// on failure this THROWS with operation context — callers render the shared
// error state (components/states.tsx). Never return fabricated defaults here.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`API ${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => request<Meta>("/meta"),
  grids: (uptae: string, bbox: [number, number, number, number]) =>
    request<GridCell[]>(`/grids?uptae=${encodeURIComponent(uptae)}&bbox=${bbox.join(",")}`),
  recommend: (uptae: string, districts: string[], top = 24) =>
    request<GridDetail[]>(
      `/recommend?uptae=${encodeURIComponent(uptae)}&districts=${encodeURIComponent(districts.join(","))}&top=${top}`,
    ),
  gridDetail: (gridId: string, uptae: string) =>
    request<GridDetail>(`/grid/${encodeURIComponent(gridId)}?uptae=${encodeURIComponent(uptae)}`),
  atPoint: (lon: number, lat: number, uptae: string) =>
    request<GridDetail>(`/at?lon=${lon}&lat=${lat}&uptae=${encodeURIComponent(uptae)}`),
  economics: (input: EconomicsInput) =>
    request<EconomicsResult>("/economics", { method: "POST", body: JSON.stringify(input) }),
  report: (gridId: string, uptae: string) =>
    request<{ sentences: string[] }>("/report", {
      method: "POST",
      body: JSON.stringify({ gridId, uptae }),
    }),
};
