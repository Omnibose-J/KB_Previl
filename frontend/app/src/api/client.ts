import type {
  BuildingsResponse,
  EconomicsInput,
  EconomicsResponse,
  GoodwillInput,
  GoodwillResponse,
  GridDetail,
  GridsResponse,
  Meta,
  RecommendResponse,
  ReportResponse,
} from "./types";

/**
 * Failure carries the status so screens can say something true about WHY.
 * The codes are lane B's error contract: 404 no scored grid · 413 viewport cap
 * exceeded · 422 bad input · 502 LLM whitelist violation · 503 a dependency
 * (read-only DB, survival curve, Seoul average, OpenAI) is unavailable.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    readonly detail: string,
  ) {
    super(`API ${status} ${path}${detail ? ` — ${detail}` : ""}`);
    this.name = "ApiError";
  }
}

// Single trust boundary for all server data. No-mock rule (ui-spec §1):
// on failure this THROWS with operation context — callers render the shared
// error state (components/states.tsx). Never return fabricated defaults here.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new ApiError(res.status, path, await readDetail(res));
  }
  return res.json() as Promise<T>;
}

/** FastAPI puts the message in `detail`; a non-JSON body must not mask the status. */
async function readDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? "");
  } catch {
    return "";
  }
}

export const api = {
  meta: () => request<Meta>("/meta"),
  grids: (uptae: string, bbox: [number, number, number, number]) =>
    request<GridsResponse>(`/grids?uptae=${encodeURIComponent(uptae)}&bbox=${bbox.join(",")}`),
  recommend: (uptae: string, districts: string[], top = 20) =>
    request<RecommendResponse>(
      `/recommend?uptae=${encodeURIComponent(uptae)}&districts=${encodeURIComponent(districts.join(","))}&top=${top}`,
    ),
  gridDetail: (gridId: string, uptae: string) =>
    request<GridDetail>(`/grid/${encodeURIComponent(gridId)}?uptae=${encodeURIComponent(uptae)}`),
  buildings: (gridId: string) =>
    request<BuildingsResponse>(`/grid/${encodeURIComponent(gridId)}/buildings`),
  /** No caller yet — reserved for the P1 diagnosis flow (S1 "이 자리 어때?"). */
  atPoint: (lon: number, lat: number, uptae: string) =>
    request<GridDetail>(`/at?lon=${lon}&lat=${lat}&uptae=${encodeURIComponent(uptae)}`),
  economics: (input: EconomicsInput) =>
    request<EconomicsResponse>("/economics", { method: "POST", body: JSON.stringify(input) }),
  goodwill: (input: GoodwillInput) =>
    request<GoodwillResponse>("/goodwill", { method: "POST", body: JSON.stringify(input) }),
  report: (gridId: string, uptae: string) =>
    request<ReportResponse>("/report", {
      method: "POST",
      body: JSON.stringify({ gridId, uptae }),
    }),
};
