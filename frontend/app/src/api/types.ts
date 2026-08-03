// 서버 ↔ 화면 계약. 정본은 service/app.py 의 Pydantic 모델이고 이 파일은 사본이다.
//
//   JSON camelCase · 좌표 [lon, lat] WGS84 · 비율 0..1 · 금액 만원(별도 표기 없으면)
//   grade 1..9, 1 이 가장 좋다 · 응답에 score 는 없다
//
// score 를 안 내는 이유: 모델 확률이 2.7~6.7%p 낙관적이라, 화면은 그 등급에서
// 실제로 관측된 생존율을 대신 보여준다.
//
// 아래 `| null` 은 전부 의미가 있다. NULL 은 «관측되지 않음»이고 0 으로 그리면
// 안 된다. 아직 항상 null 로만 오는 필드: openings36m · signal · n/ciLow/ciHigh.

/** grade 1 = best. Shares are 내신형 (4/7/12/17/20/17/12/7/4%), so grade 1 is
 *  the top ~4%, not a decile. Direction is part of the API contract. */
export type Grade = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;

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

/** 5y is a SEPARATE cohort (2019-2021) — never drawn as one curve with 1·2·3y. */
export interface SurvivalPeriod {
  years: 1 | 2 | 3 | 5;
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

export interface SurvivalYear {
  year: number;
  survival: number;
  opened: number;
}

export interface UpfrontHint {
  /** 만원 — 가맹비+교육비+기타(인테리어 등). 보증금·권리금은 안 들어 있다. */
  value: number;
  year: number;
  label: string;
  /** 정확히 같은 업종이 아니라 인접 업종 평균으로 대신한 값 */
  proxy: boolean;
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
  /** 권리금 참고가를 낼 수 있는 업태. 상권분석 분류에 대응 코드가 없는 업태는
   *  빠진다(다른 업종 벤치마크를 빌리지 않는다). 격자별 조건이 아니라 업태의
   *  정적 성질이라, 화면은 요청 전에 이 목록으로 막는다. */
  goodwillSupportedUptae: string[];
  /** 공정위 창업비용 참고값(업태별). 데이터 미적재면 빈 객체 — 힌트를 그리지
   *  않는다. label 이 근거·연도·«보증금·권리금 제외»를 다 말하므로 값을 라벨
   *  없이 단독으로 그리지 말 것. 계산에 넣는 값이 아니라 표시 전용이다. */
  upfrontHelper: Record<string, UpfrontHint>;
  gradeDirection: "1_is_best";
  /**
   * 서울 전체 개업연도별 3년 생존율. 3년이 다 지난 완결 코호트만 담기므로
   * 마지막 해는 «올해»가 아니다 — 축 라벨을 서버 값 그대로 쓸 것.
   */
  seoulSurvivalTrend: SurvivalYear[];
  /** mandatory caveat strings (grade-1 ~20% failure line) — render, don't rewrite */
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
  /** false = outside every trade area (49.5%); sales views hatch these */
  salesAvailable: boolean;
}

export interface StationAnchor {
  name: string;
  distanceM: number | null;
  stations500m: number | null;
}

/** 변동 종류. recalibration 을 grade 와 같이 다루면 «기준이 바뀐 것»이
 *  «당신 자리가 나빠진 것»으로 읽힌다. */
export type ChangeKind = "grade" | "recalibration" | "becameScorable" | "becameUnscorable";

export interface ChangeEvent {
  kind: ChangeKind;
  beforeAsOf: string;
  afterAsOf: string;
  beforeGrade: number | null;
  afterGrade: number | null;
  scoreShift: number | null;
}

export interface ChangeBucket {
  /** 6개월 구간. 경계는 고정(1~6월 / 7~12월) */
  from: string;
  to: string;
  opened: number;
  closed: number;
}

/**
 * 주변 300m 의 개업·폐업 건수. 사실이지 예측이 아니다.
 *
 * 등급 시계열이 아니다. 등급은 상대 순위라 내 자리가 그대로여도 남이 움직이면
 * 바뀌고(6개월에 등급 폭의 61% 이동), 그걸 선으로 그리면 요동이 추세로 읽힌다.
 *
 * `null` = 이 링에 인허가 이력이 아예 없음. 사건이 0 인 구간은 행으로 온다.
 */
export interface ChangeHistory {
  unit: string;
  bucketMonths: number;
  buckets: ChangeBucket[];
  /** 점수를 다시 매긴 시점. 막대 위에 표시해 «자를 바꾼 때» 를 알린다. */
  runs: { asOf: string }[];
}

export interface ChangesResponse {
  /** false = «변동 없음»이 아니라 «견줄 이전 판이 아직 없음» */
  available: boolean;
  reason: string | null;
  baselineAsOf: string | null;
  currentAsOf: string | null;
  event: ChangeEvent | null;
  sentence: string | null;
  history: ChangeHistory | null;
}

export interface Competition {
  /** 업태 무관 — 이 칸에서 영업 중인 «음식점 전체» */
  shopsHere: number | null;
  shopsNeighbor: number | null;
  /** 선택한 업태로 인허가된 «영업 중» 점포 — 이 칸 / 3x3 링(중심 포함).
   *  까페는 휴게음식점 표에서 세지만 뜻은 같다(서버가 정한다). */
  sameUptaeHere: number | null;
  sameUptaeNeighbor: number | null;
  /** lane A backlog — null until the 36-month window column lands */
  openings36m: number | null;
  openingsTotal: number | null;
  closuresTotal: number | null;
}

/** 선택한 업태의 상권 매출 공표 여부.
 *
 *  `available` 은 «상권 안이냐», 이쪽은 «그 안에서 그 업종 매출이 공표됐느냐».
 *  서울 상권분석 매출은 카드 기반 추정이라 점포가 한두 곳이면 개별 사업자
 *  매출이 드러나 공표하지 않는다(점포 1곳 공표율 9.7% · 20곳 이상 99.2%).
 *  그래서 «없음» 자체가 «이 상권엔 그 업종이 거의 없다» 는 관측이다. */
export interface UptaeSales {
  /** 이 상권의 그 업종 점포 수. 업태 대응이 없으면 null */
  uptaeStores: number | null;
  uptaePublished: boolean;
}

export interface AreaSurvival {
  rate: number | null;
  sample: number | null;
}

export interface ConceptCount {
  concept: string;
  shops: number;
}

/**
 * 주변 3x3 링(약 300m)에서 상호명으로 분류된 영업중 점포 구성. 관측 집계이지
 * 예측이 아니다 — 등급·생존율과 연결하지 않는다.
 *
 * `available: false` = 배치 미실행, `items: []` = 구성이 잡히지 않는 격자.
 * 두 상태를 같게 그리면 없는 것을 없다고 말할 수 없다.
 */
export interface ConceptMix {
  available: boolean;
  items: ConceptCount[];
  shops: number;
  source: string | null;
  claim: string | null;
}

export interface SalesMixCount {
  induty: string;
  amount: number;
  count: number;
  share: number | null;
}

/**
 * 상권의 업종별 결제 구성. `ConceptMix` 의 짝이고 둘은 실제로 다르다 — 상권
 * 1,185곳에서 커피는 가게 27.8% / 결제 24.7%, 한식은 가게 31.8% / 결제 55.1%.
 * 가게 수로 업종 수요를 짐작하면 이만큼 틀린다.
 *
 * `available: false` = 상권 밖(격자의 49.5%)이거나 표가 없음, `items: []` =
 * 상권 안인데 공표된 요식 업종이 없음.
 */
export interface SalesMix {
  available: boolean;
  items: SalesMixCount[];
  quarter: string | null;
  totalAmount: number | null;
  unit: string;
}

export interface PartyCount {
  party: "family" | "work";
  label: string;
  posts: number;
  share: number | null;
  /** 이 라벨의 정밀도. §J-1 재판정에서 코퍼스가 섞여 파일럿 값이 전체를 설명하지
   *  못하게 됐고, 그래서 서버는 **지금 항상 null** 을 보낸다. 숫자가 다시 오면
   *  그때는 화면에 반드시 함께 내야 한다 — 정확도를 빼고 라벨만 보이면
   *  «측정했다» 가 «맞다» 로 읽힌다. */
  precision: number | null;
}

/**
 * 방문객 글에서 뽑은 «누구와 왔는가». 상권 해상도라 같은 상권 안 격자는 같은
 * 값이고, 등급·순위에 쓰이지 않는다. 표기 문턱을 통과한 두 클래스만 오므로
 * 화면이 거를 필요가 없다.
 *
 * `available: false` = 수집 미실행, `items: []` = 글이 모자라 판단 불가.
 */
export interface VisitorParty {
  available: boolean;
  items: PartyCount[];
  postsScanned: number;
  labelled: number;
  unit: string;
  source: string | null;
  claim: string | null;
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
export interface Sales extends UptaeSales {
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
  conceptMix: ConceptMix | null;
  salesMix: SalesMix | null;
  visitorParty: VisitorParty | null;
  areaSurvival: AreaSurvival;
  demand: Demand;
  sales: Sales;
  signal: MarketSignal;
  /** 비어 있는 축. confidence 와 «독립»이다 — full 은 «상권 내» 라는 뜻이지
   *  «전부 채워짐» 이 아니다. 상권 안 11,901격자 중 416곳은 그 상권의 그 분기
   *  매출 행이 없어 full 인 채로 sales 가 비어 있다. */
  missingAxes: string[];
  resolutions: Resolutions;
}

/** 지도 이동용 행정동. center 는 그 동 안 채점된 격자 중심의 평균 — 값이 아니라
 *  «날아갈 곳» 이다. */
export interface Area {
  district: string;
  admDong: string;
  center: Point;
  gridCount: number;
}

export interface AreasResponse {
  items: Area[];
}

/** 격자의 대략 주소. 100m 칸은 여러 번지에 걸치므로 부번을 뗀 본번까지만 말한다
 *  — precision 이 «어디까지 좁혔는지» 를 밝힌다. */
export interface GridAddress {
  gridId: string;
  district: string | null;
  admDong: string | null;
  jibun: string | null;
  label: string | null;
  precision: "jibun" | "dong" | null;
  /** 이 칸에서 주소가 읽힌 인허가 건수와, 그 중 label 에 동의한 건수 */
  records: number;
  agree: number;
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

/** 건물 외곽선. VWORLD 에서 그때그때 받아 오는 표기 전용 자료라 등급·순위와
 *  아무 관계가 없다. `BuildingFacts` 와 별개다 — 저쪽은 인허가에서 나온 사실,
 *  이쪽은 모양뿐이고 둘을 이어 붙이지 않는다. */
export interface BuildingFootprint {
  name: string | null;
  floors: number | null;
  /** 바깥 링만. [[lon, lat], ...] 이고 첫 점과 끝 점이 같다. */
  rings: [number, number][][];
}

export interface FootprintsResponse {
  gridId: string;
  source: string;
  buildings: BuildingFootprint[];
  cached: boolean;
}

export interface RunwayInput {
  gridId: string;
  uptae: string;
  budget: number; // 만원, user input — never from data
  upfront: number; // 만원
  rentMonthly: number; // 만원
  /** omit to use this grid's trade-area figure, else the Seoul average */
  revenueMonthly?: number;
  /** pre-rent margin, default 0.25 server-side (same concept as before) */
  margin?: number;
  /** ramp-up preset — how fast revenue reaches steady state */
  rampMonths?: 3 | 6 | 9;
}

export interface RunwayMonth {
  month: number;
  revenue: number;
  net: number;
  /** cumulative net cash flow since opening (만원) */
  cum: number;
}

export interface RunwayAssumption {
  label: string;
  value: number;
  source: string;
}

export interface RunwayResponse {
  gridId: string;
  uptae: string;
  level: "IMPOSSIBLE" | "DANGER" | "WARN" | "OK";
  revenueMonthly: number;
  revenueSource: "user_input" | "trade_area_average" | "seoul_trade_area_average";
  revenueAsOfQuarter: string | null;
  budget: number;
  upfront: number;
  /** budget − upfront: what is left after signing (만원) */
  reserve: number;
  /** |trough of the cumulative curve| — the money the ramp actually burns */
  workingCapitalNeed: number;
  /** reserve ÷ need; null when nothing to bridge or the signing itself fails */
  coverage: number | null;
  /** first month the remaining money goes below zero. null = survives 24m —
   *  except under IMPOSSIBLE, where the signing itself fails and a strong
   *  month 1 can keep the curve above zero */
  depletionMonth: number | null;
  /** first month with a positive net — null = never within the horizon */
  breakevenMonth: number | null;
  troughMonth: number;
  horizonMonths: number;
  rampMonths: number;
  curve: RunwayMonth[];
  assumptions: RunwayAssumption[];
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

/**
 * 호가 3분해 (개발명세서 §5.3 후반 — 규칙 기반, ML 아님).
 * 시설 ← tangible(감가 잔존), 영업 ← intangible(초과이익 환원),
 * 바닥 ← asking − 시설 − 영업 (잔차).
 *
 * `floorKey`는 **음수일 수 있고 음수 그대로 렌더한다** — 호가가 산정근거보다
 * 낮다는 사실이지 계산 실패가 아니다. 0으로 깎으면 "근거보다 싸게 부르는
 * 자리"를 "근거만큼 부르는 자리"로 바꿔버린다.
 */
export interface GoodwillDecomposition {
  facility: number;
  business: number;
  /** 잔차 — 음수 가능. clamp 금지 (호가 < 시설+영업이라는 사실이다) */
  floorKey: number;
}

export interface GoodwillResponse {
  gridId: string;
  uptae: string;
  grade: Grade;
  askingGoodwill: number;
  decomposition: GoodwillDecomposition;
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
  valuationYears: number; // min(기대 존속, 임대차 잔여, 36개월 곡선) — 소수 연차
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
  /** 우리 산식과 무관한 외부 실태조사값. 서울 × 음식점업 한 덩어리라 자리별로
   *  다르지 않다 — 추정가를 «시장에서는 이만큼» 과 나란히 놓는 용도다.
   *  수집을 건너뛴 설치에서는 null 이고, 그때는 줄을 그리지 않는다. */
  marketAnchor: MarketAnchor | null;
  notice: string;
}

/** 부동산원 상가건물 임대차 실태조사. 금액 단위는 만원, 비율은 %. */
export interface MarketAnchor {
  region: string;
  industry: string;
  period: string;
  source: string;
  median: number;
  mean: number;
  perM2: number;
  hasGoodwillRate: number;
}

/** 부동산원 층별 효용비율. **표기 전용** — 실질 점유비용 계산에는 안 들어간다.
 *  1층·2층·지하1층만 조사되므로 나머지 층은 null 이다. */
export interface FloorReference {
  floor: string;
  utilityRatio: number;
  firstFloorRent: number;
  unit: string;
  period: string;
  source: string;
}

/** 부동산원 소규모 상가 임대료 분포. `percentile` 은 입력 임대료가 조사 상권
 *  안에서 서는 위치이고, 조사 대상은 주요 상권이라 서울 대표 표본이 아니다.
 *  임대료나 면적이 비면 null — 0 으로 셈해 «최저가»로 만들지 않는다. */
export interface MarketRent {
  /** 넣은 임대료를 ㎡당 천원으로 환산한 값. 화면이 다시 셈하면 서버 산식의
   *  사본이 되므로 환산도 서버가 한다. 임대료·면적이 비면 null. */
  userPerM2: number | null;
  seoulAvg: number;
  vacancy: number | null;
  period: string;
  unit: string;
  areaCount: number;
  min: number;
  max: number;
  percentile: number | null;
  source: string;
}

// --- 실질 월 점유비용 · 후보 비교 -------------------------------------------
//
// 보증금·월세·권리금은 형태만 다른 같은 자리값이다. 한 달치로 환산하면 순위가
// 뒤집힌다.
//
//   실질 월 점유비용 = 월세 + 관리비
//                    + 보증금 × opportunityRate ÷ 12       (돌려받으므로 이자만)
//                    + 권리금 × (1 − 승계확률) ÷ horizonMonths
//
// 서버의 순수 함수이고 클라이언트는 다시 계산하지 않는다. 두 곳에서 계산하면
// 반올림만 어긋나도 화면과 리포트가 다른 숫자를 말한다.

/**
 * 서버는 `extra="forbid"`다 — 여기 없는 키를 하나라도 보내면 422다.
 * 필드명·중첩은 `service/app.py`의 Pydantic 모델이 정본이고, 이 파일은 그걸
 * 옮긴 것이다. 마음대로 예쁘게 고치면 런타임에서만 터진다.
 */
export interface CostParams {
  /** 보증금 기회비용 연이율 */
  opportunityRate?: number;
  /** 권리금 상각 기간(개월) */
  horizonMonths?: number;
}

export interface CostBreakdown {
  rent: number; // 만원/월
  maintenance: number;
  depositOpportunity: number;
  /** 권리금 중 못 건지는 몫의 월할. 서버 이름이 premium* 이다 */
  premiumAmortized: number;
  effectiveMonthlyCost: number;
}

/** 위치는 gridId **또는** lon+lat 중 하나만. 둘 다 주면 422다. */
export interface CandidateValues {
  gridId?: string;
  lon?: number;
  lat?: number;
  deposit: number; // 만원 — 사용자 입력, 데이터에서 오지 않는다
  monthlyRent: number; // 만원
  askingGoodwill: number; // 만원 — 0 = 무권리
  areaM2: number; // 필수
  /** 필수. 지하는 음수(-1 = B1) */
  floor: number;
}

export interface CandidateInput extends CandidateValues {
  /** 화면이 붙인 고유 이름(A·B·C). 서버가 그대로 되싣는다 — 같은 격자에 후보가
   *  둘일 수 있어(같은 건물 다른 층) gridId로는 후보를 구분할 수 없다. */
  label?: string;
}

export interface EstimateInput extends CandidateValues {
  uptae: string;
  costParams?: CostParams;
}

export type RecoverySource = "constant" | "survival_curve_proxy" | "m2";

export interface EstimateResponse {
  gridId: string;
  uptae: string;
  grade: Grade;
  /** 서버가 입력을 되싣는다 — 화면이 자기가 보낸 값을 다시 기억할 필요가 없다 */
  deposit: number;
  monthlyRent: number;
  askingGoodwill: number;
  areaM2: number;
  floor: number;
  /** `P(승계) × E[지불비율]` 중 앞항만. 지불비율 원천은 미확보다. */
  successionProb: number | null;
  /** 서버가 실제로 선택한 승계 확률 원천. */
  recoverySource: RecoverySource;
  /** 대표값은 **회수율 0** 시나리오다 — 권리금을 한 푼도 못 건진다고 본 보수적
   *  기준선. 승계 확률은 회수율의 «상한»이지 기댓값이 아니므로(model-findings
   *  §21-C), 계약 앞둔 사용자에게 비용을 낮게 부르는 쪽으로 잡지 않는다. */
  effectiveCost: number;
  /** 회수율 · 상각기간 · 기회비용이자율을 흔든 그리드의 5~95 백분위.
   *  폭이 좁으면 «가정이 바뀌어도 결과가 같다», 넓으면 «판단하기 어려운 자리». */
  effectiveCostBand: { low: number; high: number };
  costBreakdown: CostBreakdown;
  /**
   * 상권 단위 추정매출. **매물 단위가 아니다** — 같은 상권 후보끼리는 같은 값이
   * 들어온다. 격자·매물로 분해하지 않는다는 결정의 결과다.
   */
  monthlyRevenue: number | null;
  revenueAsOfQuarter: string | null;
  revenueResolution: "trade_area";
  /** null = 상권 밖이라 매출 근거 없음. **0으로 그리지 않는다** */
  burdenRate: number | null;
  /** 비용 밴드 ÷ 월매출. 매출이 없으면 null — 비용 밴드는 그때도 나온다 */
  burdenRateBand: { low: number; high: number } | null;
  /** 비어 있는 축 이름 — 화면은 채우지 않고 비었다고 말한다 */
  missingAxes: string[];
  /** 부동산원 참고값 둘. 계산에 안 들어가고, 없으면 null 이라 줄이 사라진다. */
  floorReference: FloorReference | null;
  marketRent: MarketRent | null;
  notice: string;
  /** 서버가 생략된 입력까지 채워 실제 계산에 쓴 값. 화면 각주의 유일한 근거다. */
  paramsUsed: Required<CostParams>;
}

export interface CompareInput {
  uptae: string;
  /** 1~3건. 범위를 벗어나면 422 */
  candidates: CandidateInput[];
  costParams?: CostParams;
}

export interface CompareItem extends EstimateResponse {
  /** 보낸 label을 그대로 되싣는다. 안 보냈으면 null */
  label: string | null;
  /** 월세 오름차순 — 부동산 앱이 보여주는 순서 */
  rentRank: number;
  /** 실질 월 점유비용 오름차순 — 우리 순서 */
  teoRank: number;
  /** true = 이 후보의 매출이 다른 후보와 동점 → 부담률로 줄 세울 수 없다 */
  revenueTied: boolean;
}

export interface CompareResponse {
  uptae: string;
  revenueResolution: "trade_area";
  recoverySource: RecoverySource;
  paramsUsed: Required<CostParams>;
  items: CompareItem[];
}
