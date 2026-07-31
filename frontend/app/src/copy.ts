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
/** recordSince 는 «기록이 실제로 쌓이기 시작한» 연대다. DB 의 최소 개업연도는
 *  1900 이지만 1960년 이전 389건은 «꼬꼬치킨(1900)»·상호 «.» 같은 입력 오류이고
 *  전부 폐업 상태다. 밀도가 생기는 것은 1980년대(44,211건)부터라 그렇게 적는다.
 *  이전 표기 «1924년부터» 는 DB 어디에도 근거가 없었다. */
export const PROVENANCE = {
  recordCount: "53.5만 건",
  recordSince: "1980년대부터",
} as const;

/** Data actually used. The mockup listed 인스타·블로그·리뷰 — measured twice,
 *  contributed nothing, so naming them would be a claim we cannot defend. */
export const SOURCES = [
  "인허가 이력 (일반음식점 · 휴게음식점)",
  "서울 상권 추정매출",
  "서울시 생활인구",
  "전국사업체조사",
  "지하철 접근성",
] as const;

/** S1 feature cards — 6 near-duplicate slots merged into 3 distinct claims
 *  (2026-07-27 UX critique: ③④⑤ restated ①). */
/** 본문은 제목을 풀어 쓰지 않는다 — 제목이 못 하는 말만 한다. ①은 바로 아래
 *  실측 두 줄이 이어지므로 «무엇을 보여준다»가 아니라 «추정이 아니다»를 말하고,
 *  ②는 예시가 곧 근거라 한 문장으로 붙이고, ③은 무엇이 바뀌는지만 남긴다. */
export const FEATURES_3 = [
  {
    title: "등급 뒤에 진짜 숫자",
    body: "추정이 아니라 그 등급 자리들이 실제로 버틴 비율이에요.",
  },
  {
    title: "업종 따라 다른 자리",
    body: "한식이 잘되는 자리와 카페가 잘되는 자리는 달라서, 업종별로 따로 평가해요.",
  },
  {
    title: "조건 바꾸면 바로 재계산",
    body: "업종·동네·임대료를 바꾸면 추천과 손익이 같이 바뀌어요.",
  },
] as const;

export const TEAM = ["소범진", "이희수", "최지연"] as const;
