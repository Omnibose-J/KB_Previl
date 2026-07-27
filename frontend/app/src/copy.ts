// Static copy that states WHAT WE BUILT, not what the model measured.
//
// The hard line (ui-spec §4 수치 단일 출처): anything the model produces —
// survival rates, grid counts, grade bounds, AUC, failure share — comes from
// the API and MUST NOT appear here, because a model recalculation has to move
// the screen automatically. What lives here is dataset provenance: facts fixed
// by the pipeline itself (CLAUDE.md 현재 수치 · docs/data-inventory.md), which
// no rescoring can change.

/** Source-record scale (docs/data-inventory.md). Validation windows are NOT
 *  stated here — they are lineage-dependent and come from the API
 *  (survivalByPeriod.testWindow). */
export const PROVENANCE = {
  recordCount: "53.5만 건",
  recordSince: "1924년부터",
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

/** S1 feature cards — 6 near-duplicate slots merged into 3 distinct claims
 *  (2026-07-27 UX critique: ③④⑤ restated ①). */
export const FEATURES_3 = [
  {
    title: "기록으로 매긴 등급",
    body: "같은 등급을 받았던 자리들이 실제로 몇 곳이나 3년을 버텼는지 세었습니다. 등급을 매길 때 쓰지 않은 뒷 기간의 기록으로 확인한 숫자입니다.",
  },
  {
    title: "업종마다 다른 등급",
    body: "한식에 좋은 자리와 카페에 좋은 자리는 다릅니다. 12개 업태 각각 따로 매깁니다.",
  },
  {
    title: "조건을 바꾸면 다시 계산",
    body: "업종·범위·임대료를 바꾸면 추천과 손익, 권리금 참고가가 그 자리에서 다시 계산됩니다.",
  },
] as const;

export const TEAM = ["소범진", "이희수", "최지연"] as const;
