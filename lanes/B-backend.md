# 레인 B — 백엔드

**소유**: `service/` (단 `service/precompute.py`는 레인 A 소유)
**읽기만**: `pipeline/`, `model/`, `kb.db`
**쓰기 금지**: `kb.db` — 레인 A만 쓴다

---

## 지금 있는 것

`service/api.py` — SQLite 읽기 전용 조회 계층. HTTP 형태는 아래 B→C 계약으로 확정.

- `meta()` — 업태·자치구 목록, 등급별 실측 생존율, 모델 성능·한계
- `recommend(uptae, districts=(), top=24)`
- `grid_detail(grid_id, uptae)` / `at_point(lon, lat, uptae)`

**HTTP 구현: `service/app.py`** — `ui-spec.md` §7의 7종과 `/goodwill`을 실제 원천에 연결했다. 실행: `uvicorn service.app:app --reload --port 8000`. FastAPI 0.140.0 / starlette 1.3.1 (2026-07-27 호환 정비 — 0.115.6+starlette 1.0 조합은 임포트가 깨졌었다).

## 데이터 원천

`grid_score` **229,356행** (12업태 × 19,113격자). 레인 A가 생성. 조회는 인덱스 타므로 즉시.

```sql
grid_score(uptae, grid_id, score, grade, observed)   -- grade 1 = 최상
score_meta(k, v)                                     -- as_of, observed_by_grade, overall_survival 등
```

`service/precompute.py`는 등급 경계를 만든 동일한 홀드아웃의 인허가 이력
7,915건으로 등급별 0~36개월 실측 생존곡선을 계산해
`score_meta.survival_curves_36m`에 JSON으로 저장한다.

```json
{
  "rankModel": "gbm",
  "rankFeatures": ["open_cnt", "open_cnt_r1"],
  "trainYears": [2005, 2006, 2022],
  "testYears": [2023],
  "horizonMonths": 36,
  "curves": [
    {
      "grade": 1,
      "n": 791,
      "survival": [1.0, 0.99873578, 0.75474083]
    }
  ]
}
```

실제 응답에서는 `rankFeatures` 전체와 등급 1~10 각각의 `survival` 37개
값(0개월부터 36개월까지)을 싣는다. 위 예시는 구조만 보이도록 배열을 줄였다.
서빙은 JSON의 `rankModel`·`rankFeatures`를 같은 행의 `score_meta.rank_model`·
`rank_features`와 대조하고, `trainYears`·`testYears`도
`score_meta.rank_train_years`·`rank_test_years`와 대조한다. 누락·형식 오류·
계보 불일치는 합성하지 않고 `503 "배치 미실행..."` 또는 배치 계보 오류로
실패한다.

2026-07-27 원본 DB의 임시 복사본에서 배치를 실행한 결과:
`grid_score=229,356`, 곡선 표본 합계 `7,915`, 등급별 37점, 36개월 곡선과
`observed_by_grade` 최대 차이 `0.00004242`(기존 4자리 저장 반올림 이내).
동일 적합 모델 재사용 후 배치 시간은 `34초`였다. 원본 `kb.db`는 변경하지
않았다.

조인 대상: `grid_feature`(격자 피처) · `grid_sgis`(행정동명) · `grid_access`(지하철)

## 응답에 반드시 지켜야 할 것

1. **`observed`를 쓰고 `score`를 노출하지 않는다.** 모델 확률은 2.7~6.7%p 낙관 편향이라, 등급에서 실제로 관측된 생존율을 보여준다.
2. **NULL은 NULL로.** 매출 없는 격자(46.8%)를 0으로 내보내면 UI가 "최악의 입지"로 그린다. `available: false` 같은 플래그로 구분.
3. **출처 해상도를 함께 준다.** 생활인구·사업체는 행정동, 매출·유동인구는 상권(반경 ~151m), 경쟁·이력은 격자. `api.RESOLUTION` 참고.
4. **한계 문구를 meta에 싣는다.** 1등급 폐업률은 현재
   `observed_by_grade[0]`에서 계산하고, AUC 0.59가 무작위보다 나은 수준이라는
   한계를 함께 알린다.

## 손익 계산

요청 경로는 `score_meta.survival_curves_36m`의 실측 곡선을 읽고 손익 산식만
계산한다. `model.*`을 import하거나 모델을 적합하지 않는다. 곡선이 없으면
합성·요청 시 계산 없이 `503 "배치 미실행..."`이다.

- **임대료는 사용자 입력.** 공개 데이터는 전국 368개 권역이라 매물 단위로 못 쓴다
- **마진은 임대료 차감 전 값(기본 0.25).** 공표 영업이익률(10~15%)을 그대로 넣으면 임대료 이중 차감

## 환경

DB 경로는 `pipeline.config.DB_PATH`. 환경변수 `KB_DB`로 덮어쓸 수 있다(worktree 대응). 키는 `pipeline.config.load_env()`로 읽는다 — 직접 파싱하지 말 것.

## 레인 C와의 계약

**UI 스펙 확정 — `frontend/design/ui-spec.md`.** 아래 엔드포인트·응답 스키마가 B의 단일 계약이다.

C는 **목업 데이터 금지** 정책이라 실 API만 소비한다. `api.py` 조회 함수 4종이 스펙의 플로우와 대응한다(`at_point` = "이 자리 어때?" 진단 모드). 구현된 계약은 격자 폴리곤 위경도 변환(EPSG:5179 노출 금지) · `score_meta`의 등급별 생존율(+CI, A1 산출 후) 동봉 · **등급 방향(grade 1 = 최상) 명시** · What-if 임대료 재계산을 포함한다.

---

## B → C 확정 HTTP 계약 (2026-07-27)

기본 경로는 `/api`다. JSON 필드는 **camelCase**, 좌표는 `[lon, lat]` WGS84,
생존율·비율은 `0..1`, 금액은 별도 표기가 없으면 **만원**이다.
`grade`는 `1..10`이며 **1이 최상**이다. 어떤 응답에도 `score`는 없다.

없는 값은 `null`이며 0으로 대체하지 않는다. 아직 A가 만들지 않은
`openings36m`·`signal`·A1의 `n/ciLow/ciHigh`도 `null`이다. C는 목업·폴백을
넣지 않고 공통 NULL/에러 상태를 그린다.

### 공통 타입

```ts
type Grade = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10;
type Point = [lon: number, lat: number];
type Confidence = "full" | "partial";

interface GridCell {
  gridId: string;
  uptae: string;
  grade: Grade;
  observedSurvival: number; // 0..1, 등급별 홀드아웃 실측
  confidence: Confidence;
  polygon: Point[];         // 닫힌 링: 첫 점 = 마지막 점
  center: Point;
  salesAvailable: boolean; // 상권 포함 여부(grid_feature.has_sales_data)
}

interface GridDetail extends GridCell {
  admDong: string | null;
  district: string | null;
  nearestStation: {
    name: string;
    distanceM: number | null;
    stations500m: number | null;
  } | null;
  competition: {
    shopsHere: number | null;
    shopsNeighbor: number | null;
    openings36m: number | null;
    openingsTotal: number | null;
    closuresTotal: number | null;
  };
  areaSurvival: { rate: number | null; sample: number | null };
  demand: {
    dayPopulation: number | null;
    nightPopulation: number | null;
    businesses: number | null;
    workers: number | null;
    workerPerResident: number | null;
    populationDensity: number | null;
  };
  sales: {
    quarterlyAmount: number | null;
    quarterlyCount: number | null;
    footTraffic: number | null;
    available: boolean; // quarterlyAmount 값 자체의 관측 여부
  };
  signal: "verified" | "overheated" | null;
  missingAxes: string[];
  resolutions: Record<string, string>;
}
```

`resolutions`는 `competition.shopsHere → 격자 100m`,
`areaSurvival → 격자 3x3 (300m)`, 수요 필드 → 행정동, 매출·유동인구 →
상권(중앙값 반경 151m), 역 → 지점 실측의 실제 원천 해상도를 담는다.

### `GET /api/meta`

```ts
interface MetaResponse {
  asOf: string | null;
  uptae: string[]; // 라벨 가공 금지
  districts: string[];
  observedByGrade: Array<{
    grade: Grade;
    survival: number;
    n: number | null;
    ciLow: number | null;
    ciHigh: number | null;
  }>;
  overallSurvival: number | null;
  survivalByPeriod: Array<{
    years: 1 | 3 | 5;
    cohort: string | null;
    testWindow: string | null;
    overall: number | null;
    bench: string | null;
    bands: Array<{
      band: string;
      survival: number | null;
      ciLow: number | null;
      ciHigh: number | null;
      n: number | null;
    }> | null;
  }>;
  gradeArea: {
    gradeBands: string[];
    areaBands: string[];
    survival: Array<Array<number | null>>;
    bench: string;
  } | null;
  gridCount: number;
  gradeDirection: "1_is_best";
  caveats: string[]; // observed_by_grade[0]에서 계산한 1등급 폐업률, AUC 한계
  modelNote: string;
  resolutions: Record<string, string>;
}
```

A1이 적재할 `score_meta` 키는 `observed_by_grade_n`,
`observed_by_grade_ci_low`, `observed_by_grade_ci_high`(등급 1→10 CSV)로
확정한다. 키가 없으면 해당 필드는 `null`이다.

기간별 필드는 항상 1·3·5년 객체를 각각 유지한다. 1·3년 `cohort`는 `2023`,
5년은 `2019-2021 (코로나기)`다. 5년은 별도 코호트이므로 C는 1·3년 곡선과
이어 그리지 않는다. 기간별 원천 키가 없으면 해당 `bands`·`overall`·
`testWindow`·`bench`만 `null`이다. `testWindow`가 없으면 `cohort`도 `null`이다.

`gradeArea`는 `gradeband_labels`·`area_bands`·`observed_by_grade_area`·
`grade_area_bench` 네 키가 모두 있을 때만 객체다. 하나라도 없으면 전체가
`null`이며, 행렬의 빈 칸은 `0`이 아니라 `null`이다.

실제 `kb.db` 응답 예시:

```json
{
  "survivalByPeriod": [
    {
      "years": 1,
      "cohort": "2023",
      "testWindow": "2023-2023",
      "overall": 0.8289,
      "bench": "deploy",
      "bands": [
        {
          "band": "상위 10%",
          "survival": 0.9274,
          "ciLow": 0.9121,
          "ciHigh": 0.9402,
          "n": 1322
        },
        {
          "band": "중간 (2~9분위)",
          "survival": 0.8615,
          "ciLow": 0.8548,
          "ciHigh": 0.8679,
          "n": 10634
        },
        {
          "band": "하위 10%",
          "survival": 0.511,
          "ciLow": 0.4857,
          "ciHigh": 0.5363,
          "n": 1499
        }
      ]
    },
    {
      "years": 3,
      "cohort": "2023",
      "testWindow": "2023-2023",
      "overall": 0.5862,
      "bench": "deploy",
      "bands": [
        {
          "band": "상위 10%",
          "survival": 0.7547,
          "ciLow": 0.7236,
          "ciHigh": 0.7834,
          "n": 791
        },
        {
          "band": "중간 (2~9분위)",
          "survival": 0.602,
          "ciLow": 0.5899,
          "ciHigh": 0.614,
          "n": 6332
        },
        {
          "band": "하위 10%",
          "survival": 0.2917,
          "ciLow": 0.2611,
          "ciHigh": 0.3243,
          "n": 792
        }
      ]
    },
    {
      "years": 5,
      "cohort": "2019-2021 (코로나기)",
      "testWindow": "2019-2021",
      "overall": 0.4695,
      "bench": "legacy",
      "bands": [
        {
          "band": "상위 10%",
          "survival": 0.6214,
          "ciLow": 0.6045,
          "ciHigh": 0.6381,
          "n": 3204
        },
        {
          "band": "중간 (2~9분위)",
          "survival": 0.4684,
          "ciLow": 0.4623,
          "ciHigh": 0.4745,
          "n": 25639
        },
        {
          "band": "하위 10%",
          "survival": 0.3264,
          "ciLow": 0.3103,
          "ciHigh": 0.3428,
          "n": 3205
        }
      ]
    }
  ],
  "gradeArea": {
    "gradeBands": ["상위 10%", "중간 (2~9분위)", "하위 10%"],
    "areaBands": ["~25㎡", "25~37㎡", "37~56㎡", "56~90㎡", "90㎡~"],
    "survival": [
      [0.5491, 0.7023, 0.7318, 0.7706, 0.8106],
      [0.4663, 0.569, 0.6415, 0.7022, 0.733],
      [0.2701, 0.4726, 0.5671, 0.6392, 0.6561]
    ],
    "bench": "legacy train 2005-2018 / test 2019-2022"
  }
}
```

### 추천·격자·좌표

```ts
// GET /api/recommend?uptae&districts=강남구,서초구&top=24
interface RecommendResponse {
  uptae: string;
  districts: string[];
  totalGrids: number;
  inScope: number;
  count: number;
  items: GridDetail[];
  resolutions: Record<string, string>;
}

// GET /api/grid/{gridId}?uptae
// GET /api/at?lon&lat&uptae
type GridDetailResponse = GridDetail;

// GET /api/grids?uptae&bbox=lonMin,latMin,lonMax,latMax
interface GridsResponse {
  count: number;
  maxCells: number; // 현재 2,000
  items: GridCell[];
  resolutions: Record<string, string>;
}
```

`/grids`가 상한을 넘으면 일부만 잘라 주지 않고 `413`으로 실패한다. 지도를
확대한 뒤 다시 요청해야 한다.

### `GET /api/grid/{gridId}/buildings`

건물 단위 **사실 조회**다. 검증 등급은 여전히 격자까지만 유효하며, 이 응답은
건물 점수·순위·추천을 계산하지 않는다. 원천은 일반음식점 인허가
`licence`뿐이고 응답의 `source`에 이를 명시한다.

```ts
interface BuildingsResponse {
  gridId: string;
  source: "licence";
  buildings: Array<{
    jibun: string;
    buildingName: string | null;
    activeShops: number;
    openingsTotal: number;
    closuresTotal: number;
    uptaeMix: Array<{
      uptae: string | null;
      active: number;
    }>; // 영업 중 점포 기준 상위 3개
  }>;
  unparsedCount: number;
}
```

`licence.addr` 시작부를
`^(서울특별시\s+\S+구\s+\S+동?\s+(?:산\s*)?\d+(?:-\d+)?)`로 파싱한
지번별로 묶는다. 정규식 뒤부터 첫 쉼표 전까지의 비어 있지 않은 텍스트 중
최빈값을 `buildingName`으로 쓰고, 없으면 `null`이다. 미파싱 행은 어떤
지번으로도 추정하지 않고 그룹에서 제외하되 `unparsedCount`에 포함한다.

`activeShops` 내림차순으로만 정렬해 최대 50개를 반환한다. 알려진 격자에
인허가 행이 없으면 `200`과 빈 `buildings`가 정답이며, `grid` 테이블에
`gridId` 자체가 없을 때만 `404`다. v1에는 `uptae` 필터 파라미터가 없고,
NULL을 0이나 다른 업태로 바꾸지 않는다.

### `POST /api/estimate` · `POST /api/compare`

사용자가 이미 확보한 후보를 매물 인벤토리 없이 계산한다. 후보 위치는
`gridId` 또는 `lon`+`lat` 중 하나이며 주소를 받지 않는다. 금액은 기존 계약과
같이 만원, `areaM2`는 ㎡, `floor`는 정수 층이다.

```ts
interface CostParamsInput {
  opportunityRate?: number; // 기본 0.04
  horizonMonths?: number;   // 기본 36
}

interface CandidateValues {
  gridId?: string;
  lon?: number;
  lat?: number;
  deposit: number;
  monthlyRent: number;
  askingGoodwill: number;
  areaM2: number;
  floor: number;
}

interface CandidateInput extends CandidateValues {
  label?: string; // 비교 화면이 소유하며 응답 item에 그대로 돌아온다
}

interface EstimateInput extends CandidateValues {
  uptae: string;
  costParams?: CostParamsInput;
}

interface EstimateResponse extends CandidateValues {
  gridId: string;
  uptae: string;
  grade: Grade;
  successionProb: number; // P(승계)만. 권리금 지불비율은 미확보
  recoverySource: "constant" | "survival_curve_proxy" | "m2";
  effectiveCost: number;
  costBreakdown: {
    rent: number;
    maintenance: number;
    depositOpportunity: number;
    premiumAmortized: number;
    effectiveMonthlyCost: number;
  };
  monthlyRevenue: number | null;
  revenueAsOfQuarter: string | null;
  revenueResolution: "trade_area";
  burdenRate: number | null;
  missingAxes: string[];
  paramsUsed: {
    opportunityRate: number;
    horizonMonths: number;
  }; // 생략한 입력도 서버 기본값을 채운 실제 계산값
  notice: string;
}

interface CompareInput {
  uptae: string;
  candidates: CandidateInput[]; // 1~3건
  costParams?: CostParamsInput;
}

interface CompareItem extends EstimateResponse {
  label: string | null;
  rentRank: number;
  teoRank: number;
  revenueTied: boolean;
}

interface CompareResponse {
  uptae: string;
  revenueResolution: "trade_area";
  recoverySource: "constant" | "survival_curve_proxy" | "m2";
  paramsUsed: {
    opportunityRate: number;
    horizonMonths: number;
  };
  items: CompareItem[];
}
```

`monthlyRevenue`는 최신 공통 분기의 상권×동일 업종
`sales_amt / stor_co / 3 / 10,000`만 사용한다. 층·면적 배수로 후보에
분배하지 않는다. 상권 밖이면 비용은 계산하되 매출·부담률은 `null`이고
`missingAxes`에 `revenue`와 `burdenRate`가 남는다. 동일 업종 원천이 없으면
다른 업종이나 서울 평균으로 바꾸지 않고 `503`이다.

`/compare`는 입력 순서의 후보마다 caller가 보낸 `label`을 그대로 되싣고
`rentRank`와 `teoRank`를 함께 싣는다. 같은 `gridId`의 다른 층 후보도
`label`로 구분하며, label을 서버가 주소·층에서 추정하지 않는다.
TEO 순위는 `burdenRate` → `effectiveCost` → `successionProb` 순이며, 부담률
결측 후보는 관측 후보 뒤에 둔다. 같은 상권×업종 값을 공유하는 후보는
`revenueTied: true`라서 개별 매출 추정으로 오해하지 않게 한다.

승계 확률 출처는 `KB_RECOVERY_SOURCE`로 `constant`,
`survival_curve_proxy`, `m2` 중 하나를 명시적으로 고른다. 기본은 기존
W1~W4 계약을 보존하는 `constant`이고, 선택한 원천이 없거나 유효하지 않으면
다른 원천으로 넘어가지 않고 `503`이다. `m2`는 요청 시 모델을 실행하지 않고
배치가 만든 `succession_score`의 2022 bin별 실측 승계율만 읽는다.
서비스는 model version `m2-gbm-close-2005-2021-cal-2022-v1`과 관측월
`202607`도 함께 검증하며, 재학습이 W6 채택 문턱을 실패하면 배치가 기존
테이블 교체를 거부한다.
`successionProb`는 `P(승계)`이지 `P(승계) × E[지불비율]`이 아니다. 현재
권리금 상각은 승계 시 전액 회수를 놓은 민감도 계산이며, 실제 지불비율 원천은
확보되지 않았음을 `notice`에 밝힌다.

### `POST /api/economics`

```ts
interface EconomicsInput {
  gridId: string;
  uptae: string;
  rentMonthly: number;
  upfront: number;
  revenueMonthly?: number; // 생략 시에만 계약된 서울 상권 평균 사용
  margin?: number;         // 기본 0.25, 임대료 차감 전
}

interface EconomicsResponse {
  gridId: string;
  uptae: string;
  grade: Grade;
  revenueMonthly: number;
  revenueSource: "user_input" | "seoul_trade_area_average";
  revenueAsOfQuarter: string | null;
  simplePaybackMonths: number | null;
  riskAdjustedPaybackMonths: number | null;
  expectedProfit3y: number;
  monthlyProfit: number;
  survival36m: number;
  usedSeoulAverageRevenue: boolean;
  margin: number;
  marginSensitive: boolean; // 마진 20~30%에서 기대손익 부호가 바뀌는가
  gradeComparison: Array<{ grade: Grade; expectedProfit3y: number }>;
}
```

매출 생략 시 서울 평균은 UI 스펙이 허용한 유일한 대체 경로다. 원천 행이
없으면 0을 만들지 않고 `503`이다. 등급별 실측 생존곡선은 배치가 DB에
저장하며 요청은 읽기만 한다. 곡선 누락·계보 불일치는 `503`이고 C는 목업으로
바꾸지 않는다. 2026-07-27 임시 배치 DB를 사용한 포트 8000 콜드 프로세스의
첫 실호출은 `0.058초`, HTTP 200이었다.

### `POST /api/goodwill`

호가·임대차 잔여기간·유형자산만 사용자 입력이다. 상권 매출과 서울 동일업종
벤치마크, 영업이익률, 할인율, 조정계수는 서버가 채운다. C는 응답 값을 그대로
표시하고 어떤 기반값도 계산하거나 전달하지 않는다.

```ts
interface GoodwillInput {
  gridId: string;
  uptae: string;
  askingGoodwill: number;
  leaseRemainingYears: number;
  assets?: Array<{
    name: string;
    acquisitionCost: number;
    ageYears: number;
    usefulLifeYears: number;
  }>;
}
```

서버 소유 값:

- `monthlyRevenue`: 최신 공통 분기의 해당 상권×동일업종
  `trdar_sales.sales_amt / trdar_store.stor_co / 3 / 10,000`(만원)
- `benchmarkMonthlyRevenue`: 같은 분기 서울 전체 동일업종의 상권별 점포당
  월매출 평균, `benchmarkLevel: 4`
- `operatingMargin: 0.15`: 소상공인실태조사 음식점업 영업이익률,
  **임대료 차감 후** 기준. 별도 임대료 차감 없음
- `loanRate: 0.05`, `riskPremium: 0.03`, `discountRate: 0.08`:
  v1 고정 대출금리+사업위험 프리미엄
- `adjustmentFactor: 1.0`,
  `adjustmentReasons: ["v1 미적용 — 데이터 기반 조정 항은 로드맵"]`

인허가 업태와 서울 상권분석 업종코드가 직접 대응하는 한식·식육→한식,
중국식, 일식, 경양식, 통닭, 분식, 호프/통닭·정종/대포집/소주방→호프,
까페만 계산한다. `기타`와 `외국음식전문점`은 동일업종 원천이 없으므로 다른
업종을 빌리지 않고 `503`이다.

응답은 입력·근거 필드에 더해 아래 산출을 반환한다.

```ts
interface GoodwillResponse {
  gridId: string;
  uptae: string;
  grade: Grade;
  askingGoodwill: number;
  monthlyRevenue: number;
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
  expectedSurvivalYears: number; // 36개월 실측곡선 제한평균
  valuationYears: number;        // floor(min(기대존속, 임대차 잔여))
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
  decomposition: {
    facility: number; // tangibleValue
    business: number; // intangibleValue
    floorKey: number; // askingGoodwill - facility - business, 음수 보존
  };
  adjustmentFactor: number;
  adjustmentReasons: string[];
  estimatedGoodwill: number;
  bandLow: number;  // r±3%p, N±1년, d±2%p 그리드의 5백분위
  bandHigh: number; // 같은 그리드의 95백분위
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
```

실제 슬림 요청:

```json
{
  "gridId": "9596_19536",
  "uptae": "한식",
  "askingGoodwill": 5000,
  "leaseRemainingYears": 5,
  "assets": [
    {
      "name": "주방설비",
      "acquisitionCost": 1000,
      "ageYears": 2,
      "usefulLifeYears": 5
    }
  ]
}
```

실제 응답 예시(민감도 27행 중 1행만 표시):

```json
{
  "gridId": "9596_19536",
  "uptae": "한식",
  "grade": 4,
  "askingGoodwill": 5000.0,
  "monthlyRevenue": 2998.6363146464646,
  "benchmarkMonthlyRevenue": 2225.5001901365144,
  "benchmarkLevel": 4,
  "benchmarkWarning": "동급 상권 비교가 아닌 서울 전체 동일 업종 상권 평균 대비입니다.",
  "operatingMargin": 0.15,
  "operatingMarginBasis": "after_rent",
  "operatingMarginSource": "소상공인실태조사 음식점업 영업이익률 15% (임대료 차감 후, v1 고정)",
  "loanRate": 0.05,
  "riskPremium": 0.03,
  "discountRate": 0.08,
  "discountRateSource": "소상공인 대출금리 5% + 사업위험 프리미엄 3% (v1 고정)",
  "expectedSurvivalYears": 2.506839224166666,
  "valuationYears": 2,
  "leaseRemainingYears": 5.0,
  "intangibleValue": 2481.671510772679,
  "tangibleValue": 600.0,
  "tangibleAssets": [
    {
      "name": "주방설비",
      "acquisitionCost": 1000.0,
      "ageYears": 2.0,
      "usefulLifeYears": 5.0,
      "residualRate": 0.6,
      "value": 600.0
    }
  ],
  "decomposition": {
    "facility": 600.0,
    "business": 2481.671510772679,
    "floorKey": 1918.328489227321
  },
  "adjustmentFactor": 1.0,
  "adjustmentReasons": ["v1 미적용 — 데이터 기반 조정 항은 로드맵"],
  "estimatedGoodwill": 3081.671510772679,
  "bandLow": 1636.6831556322095,
  "bandHigh": 4858.472998766654,
  "askingGap": 1918.328489227321,
  "askingGapRate": 0.6224960974981825,
  "negotiationReference": "above_band",
  "sensitivity": [
    {
      "operatingMargin": 0.12,
      "years": 1,
      "discountRate": 0.06,
      "estimatedGoodwill": 1650.2981314097433
    }
  ],
  "notice": "서울시 상권분석서비스 최신 분기 점포당 추정매출을 사용한 공개 데이터 기반 참고용 추정치이며 감정평가가 아닙니다."
}
```

상권 밖(`salesAvailable=false`)은 `422`다. 월매출·벤치마크는 0을 허용하지
않는다. 동일업종 벤치마크 또는 해당 상권 매출 원천 행이 없으면 합성 없이
`503`이다. 무형가치는 음수 초과수익만 0으로 절사한다. 영업이익률에는
임대료가 이미 포함되며 별도 임대료 차감은 없다.

### `POST /api/report`

```ts
type ReportInput = { gridId: string; uptae: string };
type ReportResponse = {
  gridId: string;
  uptae: string;
  sentences: string[]; // 총 3~5개
};
```

서버가 실제 격자·실측치 구조체를 만든 뒤 LLM에 전달한다. `gradeTopPercent`는
현재 백분위가 아닌 홀드아웃 절대 경계를 "상위 n%"로 오역하므로 evidence에
포함하지 않는다. LLM은
`{{grade}}` 같은 허용 evidence placeholder만 생성할 수 있고 숫자 글리프를 직접
쓰면 전체 응답을 폐기하고 `502`다. 서버가 placeholder를 원천 문자열로 치환하므로
분수·지수·반올림 우회도 불가능하다. 마지막 한계 문장의 폐업률은 해당
`grid_score.observed`에서 계산해 서버가 삽입한다. LLM/API 키 실패는 목업 문장
없이 `503`이다.

### 오류 계약

- `404`: 평가 대상 밖 격자. `detail`은 정확히
  `"이웃 이력 부족으로 평가하지 않음"`으로 시작
- `413`: `/grids` 셀 상한 초과
- `422`: 입력·좌표·bbox·업태·권리금 전제 위반
- `502`: LLM 구조/숫자 화이트리스트 위반
- `503`: `grid_score`가 빈 배치 미실행 상태, 읽기 전용 DB, 배치 곡선 누락·
  계보 오류, 서울 평균 매출, goodwill 동일업종 벤치마크·상권매출 원천,
  OpenAI 의존성 실패

---

## Decision log

### [[B-001-camelcase-observed-contract]]

**Decision:** 2026-07-27 — B→C JSON은 camelCase로 확정하고, 실측값이 없는 필드는 `null` 또는 명시적 에러로 남긴다.

**Context:** C 골격의 잠정 타입이 camelCase이며, B 계약은 모델 `score` 비노출·NULL 보존·원천 해상도 동봉을 강제해야 한다. A1 CI·최근 3년 개업·과열 임계값·권리금 벤치마크 생산자는 아직 미완이다.

**Why:** C의 변환 계층을 없애고 실제 API와 타입을 1:1로 맞춘다. 미완 값을 합성하지 않아 목업·폴백이 조용히 제품 수치로 굳는 것을 막는다.

**Rejected:** snake_case 응답은 C에 불필요한 변환을 만든다. 0·추정 CI·합성 생존곡선·가짜 벤치마크는 결측과 실패를 숨기므로 배제한다.

**Status:** Active

### [[B-002-batch-survival-curve-boundary]]

**Decision:** 2026-07-27 — 등급별 0~36개월 실측 생존곡선은 등급을 확정한
동일 배치가 `score_meta.survival_curves_36m` 단일 JSON으로 저장하고, 요청
경로는 이를 읽고 계보만 검증한다.

**Context:** 기존 첫 `/economics` 요청은 `model.economics.survival_curve()`를
통해 LightGBM을 다시 적합해 약 51초가 걸렸다. 또한 인허가 이력은 같은
`(grid_id, uptae, open_ym)` 키에 여러 건이 존재하므로 임의의 첫 행만 고르면
곡선 표본 계보가 깨진다.

**Why:** 보정 단계에서 만든 등급 경계를 같은 홀드아웃 메타데이터에 다시
적용하고, 중복 키의 모든 인허가 이력을 한 번씩 집계한다. 현재 격자도 경계를
만든 바로 그 적합 모델로 점수화해 절대 경계를 다른 재학습 확률에 적용하지
않는다. JSON에 `rankModel`·`rankFeatures`·학습/검증 연도·표본 수를 함께 넣고,
`score_meta.rank_model`·`rank_features`·`rank_train_years`·`rank_test_years`와
모두 대조해 곡선 계보까지 덮는다.

**Rejected:** 요청 시 모델 적합·메모리 캐시는 serving-design §1 위반이며
콜드스타트를 숨기지 못한다. 홀드아웃을 추가해 재학습한 모델에 이전 확률
경계를 적용하는 방식은 확률 척도의 동일성을 보장하지 못한다. 키별 첫 인허가
행 선택은 표본을 누락한다. 곡선 누락 시 합성 곡선은 배치 실패를 숨기므로
배제한다.

**Status:** Active

### [[B-003-server-owned-goodwill-inputs]]

**Decision:** 2026-07-27 — `/api/goodwill`은 사용자 소유 5개 필드만 받고,
상권 매출·Level 4 벤치마크·마진·할인율·조정계수는 서버가 실제 원천과
확정 v1 상수로 채운다.

**Context:** 호출자가 기반값을 전달하던 계약은 C가 값을 창작하지 않고는 호출할
수 없었다. 서울 상권분석 업종 10종과 인허가 업태 12종도 완전히 같지 않다.

**Why:** 상권·서울 벤치마크는 같은 최신 분기의 `trdar_sales`와
`trdar_store`에서 점포당 월매출로 계산한다. 음식점업 영업이익률 15%는 임대료
차감 후로 고정해 이중 차감을 막고, 할인율은 대출금리 5%+프리미엄 3%,
조정계수는 검증된 항이 없는 v1에서 1.0으로 고정한다.

**Rejected:** `기타`·`외국음식전문점`을 양식이나 전체 음식점 평균에 임의
매핑하면 "동일 업종" 주장을 어긴다. 값 누락 시 다른 업종·0·전체 평균으로
대체하는 경로는 원천 실패를 숨기므로 배제한다.

**Status:** Active

### [[B-004-shared-candidate-estimation-boundary]]

**Decision:** 2026-07-28 — Candidate source lookup, effective-cost calculation,
and deterministic ranking live in `service/estimation.py`; FastAPI models and
routes remain thin adapters in `service/app.py`.

**Context:** `/api/estimate` and `/api/compare` must use the same trade-area
revenue grain and cost formula, while W7 must later replace the fixed
succession proxy without changing route behavior.

**Why:** One shared decision point prevents the two endpoints from drifting on
NULL handling, source failures, tie-break order, or future recovery-source
selection. The module reads SQLite through the enforced read-only connection
and delegates deterministic arithmetic to `service/cost.py`.

**Rejected:** Duplicating calculations in both routes would create two public
contracts. Importing `model.*` would cross the serving boundary. Applying
floor, area, or location multipliers to trade-area revenue would invent
candidate-level data.

**Status:** Active
