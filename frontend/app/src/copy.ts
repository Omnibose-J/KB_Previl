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

/** S1 feature cards — 6 mockup cards collapsed into 3 (ui-spec §3-S1). */
export const FEATURES = [
  {
    title: "실측으로 검증된 등급",
    body: "예측 확률이 아니라, 과거에 그 등급을 받은 자리들이 실제로 몇 곳이나 3년을 버텼는지를 보여드립니다. 학습에 쓰지 않은 뒷 기간으로 검증했습니다.",
  },
  {
    title: "검증된 자리 vs 과열 신호",
    body: "이미 가게가 많은 곳은 검증된 자리, 최근 몇 년 새 급증한 곳은 과열 신호로 구분합니다. 데이터가 실제로 그 방향을 가리켰습니다.",
  },
  {
    title: "입지 위험을 반영한 손익",
    body: "같은 매출·같은 임대료여도 자리가 다르면 3년 뒤 손에 남는 돈이 갈립니다. 생존 확률을 반영한 회수 기간을 따로 계산합니다.",
  },
] as const;
