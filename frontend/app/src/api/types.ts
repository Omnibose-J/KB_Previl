// Response types for the B->C contract.
// Field names below are PROVISIONAL: lane B fixes the canonical schema in
// lanes/B-backend.md, and this file must be updated to match it 1:1.
// Numbers displayed on screen must come from these payloads (ui-spec.md §4:
// no front-end hardcoding of survival rates, grid counts, grade bounds).

/** grade 1 = best (top 10%). Direction is part of the API contract. */
export type Grade = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10;

export type Confidence = "full" | "partial";

export interface Meta {
  asOf: string;
  uptae: string[]; // render chips with these values verbatim (ui-spec §7)
  districts: string[];
  /** observed 3y survival per grade, index 0 = grade 1; with Wilson CI once A1 lands */
  observedByGrade: { survival: number; n: number; ciLow?: number; ciHigh?: number }[];
  overallSurvival: number;
  /** mandatory caveat strings (AUC framing, ~26% failure line) — render, don't rewrite */
  caveats: string[];
}

export interface GridCell {
  gridId: string;
  uptae: string;
  grade: Grade;
  observedSurvival: number;
  confidence: Confidence;
  /** WGS84 polygon corners provided by B (EPSG:5179 never crosses the API) */
  polygon: [number, number][];
}

export interface GridDetail extends GridCell {
  admDong: string; // from grid_sgis, used for card titles (ui-spec §3-S3)
  nearestStation?: { name: string; distanceM: number };
  // competition / history / demand fields: fill in from B's schema when fixed.
  // NULL fields stay null — render with the common NULL pattern (ui-spec §4).
}

export interface EconomicsInput {
  gridId: string;
  uptae: string;
  rentMonthly: number; // 만원, user input — never from data (ui-data-contract)
  upfront: number; // 만원
  revenueMonthly?: number; // 만원; absent -> Seoul average, caption required
  margin?: number; // default 0.25, pre-rent margin
}

export interface EconomicsResult {
  simplePaybackMonths: number | null;
  riskAdjustedPaybackMonths: number | null; // null = not within 36m
  expectedProfit3y: number; // 만원, survival-weighted
  usedSeoulAverageRevenue: boolean; // true -> show mandatory caption
  marginSensitive: boolean; // A2: sign flips within margin 20-30% band
}
