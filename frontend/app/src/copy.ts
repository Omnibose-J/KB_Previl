// Static copy that states WHAT WE BUILT, not what the model measured.
//
// The hard line (ui-spec §4 수치 단일 출처): anything the model produces —
// survival rates, grid counts, grade bounds, AUC, failure share — comes from
// the API and MUST NOT appear here, because a model recalculation has to move
// the screen automatically. What lives here is dataset provenance: facts fixed
// by the pipeline itself (CLAUDE.md 현재 수치 · docs/data-inventory.md), which
// no rescoring can change.

/** Source-record scale and the time-split validation window (docs/model-findings.md §4-C). */
export const PROVENANCE = {
  recordCount: "인허가 53.5만 건",
  recordSince: "1924년부터",
  validationWindow: "2013~2022년",
} as const;

/** Data actually used. The mockup listed 인스타·블로그·리뷰 — measured twice,
 *  contributed nothing, so naming them would be a claim we cannot defend. */
export const SOURCES = [
  "인허가 이력",
  "서울 상권 추정매출",
  "서울시 생활인구",
  "전국사업체조사",
  "지하철 접근성",
] as const;

/** S1 feature cards — figma keeps 6 slots (2026-07-27 rebuild); each mockup
 *  claim is swapped for what the model actually does (ui-spec §3-S1 교체 표).
 *  The SNS/타이밍 슬롯 are replaced outright: 비정형 measured twice, no lift. */
export const FEATURES_6 = [
  {
    title: "실측으로 검증된 등급",
    body: "같은 등급을 받았던 자리들이 실제로 몇 곳이나 3년을 버텼는지, 학습에 쓰지 않은 뒷 기간으로 검증해 보여드립니다.",
  },
  {
    title: "업종별 사전계산 등급",
    body: "카페와 고깃집은 좋은 자리가 다릅니다. 12개 업태 각각 등급을 따로 계산합니다.",
  },
  {
    title: "검증된 자리 vs 과열 신호",
    body: "오래 버틴 점포가 많은 곳과 최근 개업이 급증한 곳을 구분해 표시합니다.",
  },
  {
    title: "내 업종 기준 경쟁 분석",
    body: "같은 업종의 영업 점포 수·개업 추이·이웃 생존율로 경쟁 환경을 평가합니다.",
  },
  {
    title: "등급 + 격자별 근거",
    body: "등급마다 실측 생존율을 병기하고, 격자별 근거(경쟁·이력·접근성)를 함께 제시합니다.",
  },
  {
    title: "What-if 재계산",
    body: "업종·범위·임대료를 바꾸면 추천과 손익이 실제로 다시 계산됩니다.",
  },
] as const;

export const TEAM = ["소범진", "이희수", "최지연"] as const;
