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
  "상가업소 (소상공인시장진흥공단)",
  "서울 상권 추정매출",
  "서울시 생활인구",
  "전국사업체조사",
  "지하철 접근성",
] as const;

/** S1 feature cards — 6 near-duplicate slots merged into 3 distinct claims
 *  (2026-07-27 UX critique: ③④⑤ restated ①). */
export const FEATURES_3 = [
  {
    title: "등급 뒤에 진짜 숫자",
    body: "같은 등급 자리들이 실제로 얼마나 버텼는지 등급마다 함께 보여드려요.",
  },
  {
    title: "업종 따라 다른 자리",
    body: "한식이 잘되는 자리와 카페가 잘되는 자리는 달라요. 업종별로 따로 평가해요.",
  },
  {
    title: "조건 바꾸면 바로 재계산",
    body: "업종, 동네, 임대료를 바꾸면 추천과 손익이 바로 바뀌어요.",
  },
] as const;

export const TEAM = ["소범진", "이희수", "최지연"] as const;
