// B->C contract — mirrors lanes/B-backend.md (2026-07-27, decisions B-001 +
// goodwill-report-design §8-A slim input).
//
// JSON is camelCase, coordinates are [lon, lat] WGS84, rates are 0..1, money is
// 만원 unless stated. grade is 1..10 and 1 IS BEST. No response ever carries
// `score` — the model probability runs 2.7~6.7%p optimistic, so the screen
// shows the survival actually observed in that grade instead.
//
// Every `| null` below is load-bearing: NULL means "not observable" and must
// never be rendered as 0 (ui-spec §4). Fields lane A has not produced yet
// (openings36m, signal, n/ciLow/ciHigh) arrive as null and the screen draws the
// common NULL pattern rather than substituting anything.

/** grade 1 = best (top 10%). Direction is part of the API contract. */
export type Grade = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10;

/** [lon, lat] — EPSG:5179 never crosses the API. */
export type Point = [number, number];

export type Confidence = "full" | "partial";

/** Field path -> human-readable source resolution ("행정동", "상권 반경 151m"). */
export type Resolutions = Record<string, string>;

export interface ObservedGrade {
  grade: Grade;
  survival: number;
  n: number | null;
  ciLow: number | null;
  ciHigh: number | null;
}

export interface SurvivalBand {
  band: string; // holdout band label, render verbatim
  survival: number | null;
  ciLow: number | null;
  ciHigh: number | null;
  n: number | null;
}

/** 5y is a SEPARATE cohort (2019-2021) — never drawn as one curve with 1·3y. */
export interface SurvivalPeriod {
  years: 1 | 3 | 5;
  cohort: string | null;
  testWindow: string | null;
  overall: number | null;
  bench: string | null;
  bands: SurvivalBand[] | null;
}

/** Observed, not causal: area correlates with capital (serving-design §5-6). */
export interface GradeArea {
  gradeBands: string[];
  areaBands: string[];
  survival: (number | null)[][]; // [band][areaBand], null = no observation
  bench: string;
}

export interface Meta {
  asOf: string | null;
  uptae: string[]; // render chips with these values verbatim (ui-spec §7)
  districts: string[];
  observedByGrade: ObservedGrade[];
  overallSurvival: number | null;
  survivalByPeriod: SurvivalPeriod[];
  gradeArea: GradeArea | null;
  /** total scored grids — S2 funnel row 1 (never hardcode the count) */
  gridCount: number;
  gradeDirection: "1_is_best";
  /** mandatory caveat strings (AUC framing, ~26% failure line) — render, don't rewrite */
  caveats: string[];
  modelNote: string;
  resolutions: Resolutions;
}

export interface GridCell {
  gridId: string;
  uptae: string;
  grade: Grade;
  observedSurvival: number;
  confidence: Confidence;
  /** closed ring: first point equals last */
  polygon: Point[];
  center: Point;
  /** false = outside every trade area (46.8%); sales views hatch these */
  salesAvailable: boolean;
}

export interface StationAnchor {
  name: string;
  distanceM: number | null;
  stations500m: number | null;
}

export interface Competition {
  shopsHere: number | null;
  shopsNeighbor: number | null;
  /** lane A backlog — null until the 36-month window column lands */
  openings36m: number | null;
  openingsTotal: number | null;
  closuresTotal: number | null;
}

export interface AreaSurvival {
  rate: number | null;
  sample: number | null;
}

/** All 행정동-resolution: identical for every grid in the same dong. */
export interface Demand {
  dayPopulation: number | null;
  nightPopulation: number | null;
  businesses: number | null;
  workers: number | null;
  workerPerResident: number | null;
  populationDensity: number | null;
}

/** 상권 resolution (median radius 151m); absent outside trade areas. */
export interface Sales {
  quarterlyAmount: number | null;
  quarterlyCount: number | null;
  footTraffic: number | null;
  available: boolean;
}

/** Verified-vs-overheated verdict computed by lane A — never derived client-side. */
export type MarketSignal = "verified" | "overheated" | null;

export interface GridDetail extends GridCell {
  admDong: string | null;
  district: string | null;
  nearestStation: StationAnchor | null;
  competition: Competition;
  areaSurvival: AreaSurvival;
  demand: Demand;
  sales: Sales;
  signal: MarketSignal;
  /** which axes are empty when confidence = partial */
  missingAxes: string[];
  resolutions: Resolutions;
}

export interface RecommendResponse {
  uptae: string;
  districts: string[];
  totalGrids: number;
  inScope: number;
  count: number;
  items: GridDetail[];
  resolutions: Resolutions;
}

export interface GridsResponse {
  count: number;
  /** server cap; exceeding it is a 413, never a silent truncation */
  maxCells: number;
  items: GridCell[];
  resolutions: Resolutions;
}

/** Resolution ladder v1 (goodwill-report-design §5): building-level FACTS from
 *  licence records — never a building-level prediction or ranking. */
export interface BuildingFacts {
  jibun: string;
  buildingName: string | null;
  activeShops: number;
  openingsTotal: number;
  closuresTotal: number;
  /** top 3 by active count */
  uptaeMix: { uptae: string; active: number }[];
}

export interface BuildingsResponse {
  gridId: string;
  source: string;
  /** factual sort (activeShops desc), server-capped at 50 */
  buildings: BuildingFacts[];
  /** rows whose address could not be parsed — excluded, never guessed */
  unparsedCount: number;
}

export interface EconomicsInput {
  gridId: string;
  uptae: string;
  rentMonthly: number; // 만원, user input — never from data
  upfront: number; // 만원
  /** omit to use the contracted Seoul trade-area average (caption becomes mandatory) */
  revenueMonthly?: number;
  /** pre-rent margin, default 0.25 server-side */
  margin?: number;
}

export interface GradeComparison {
  grade: Grade;
  expectedProfit3y: number;
}

export interface EconomicsResponse {
  gridId: string;
  uptae: string;
  grade: Grade;
  revenueMonthly: number;
  revenueSource: "user_input" | "seoul_trade_area_average";
  revenueAsOfQuarter: string | null;
  simplePaybackMonths: number | null;
  /** null = not recovered within 36 months — a real answer, not a gap */
  riskAdjustedPaybackMonths: number | null;
  expectedProfit3y: number;
  monthlyProfit: number;
  survival36m: number;
  usedSeoulAverageRevenue: boolean;
  margin: number;
  /** sign of the 3y result flips within the 20~30% margin band */
  marginSensitive: boolean;
  gradeComparison: GradeComparison[];
}

export interface ReportResponse {
  gridId: string;
  uptae: string;
  /** 3~5 sentences; the closing limitation line is inserted server-side */
  sentences: string[];
}

// --- 권리금 리포트 (goodwill-report-design §8) -------------------------------
// Slim input: the user supplies only what the user actually knows. Benchmark,
// margins, and discount rate are SERVER-owned — the client never computes or
// forwards them (that pass-through was findings.md F-C1).

export interface GoodwillAssetInput {
  name: string;
  acquisitionCost: number; // 만원
  ageYears: number;
  usefulLifeYears: number;
}

export interface GoodwillInput {
  gridId: string;
  uptae: string;
  askingGoodwill: number; // 만원 — 호가
  leaseRemainingYears: number;
  assets?: GoodwillAssetInput[];
}

export interface GoodwillResponse {
  gridId: string;
  uptae: string;
  grade: Grade;
  askingGoodwill: number;
  monthlyRevenue: number; // 상권 단위 — caption is mandatory
  benchmarkMonthlyRevenue: number;
  benchmarkLevel: 1 | 2 | 3 | 4;
  benchmarkWarning: string | null;
  operatingMargin: number;
  operatingMarginBasis: "after_rent";
  operatingMarginSource: string;
  loanRate: number;
  riskPremium: number;
  discountRate: number;
  discountRateSource: string;
  expectedSurvivalYears: number;
  valuationYears: number; // floor(min(기대 존속, 임대차 잔여))
  leaseRemainingYears: number;
  intangibleValue: number;
  tangibleValue: number;
  tangibleAssets: Array<{
    name: string;
    acquisitionCost: number;
    ageYears: number;
    usefulLifeYears: number;
    residualRate: number;
    value: number;
  }>;
  adjustmentFactor: number;
  adjustmentReasons: string[];
  estimatedGoodwill: number;
  bandLow: number;
  bandHigh: number;
  askingGap: number;
  askingGapRate: number | null;
  negotiationReference: "below_band" | "within_band" | "above_band";
  sensitivity: Array<{
    operatingMargin: number;
    years: number;
    discountRate: number;
    estimatedGoodwill: number;
  }>;
  notice: string;
}
