// Display formatting. Every function here takes a value that ALREADY came from
// the API — none of them invent, default, or round away a missing value.
// NULL never becomes 0 (ui-spec §4): callers state 정보 없음 instead.

import type { StationAnchor } from "../api/types";

export const int = (v: number) => v.toLocaleString("ko-KR");

/** 0..1 -> "74.3%" */
export const pct1 = (v: number) => `${(v * 100).toFixed(1)}%`;

/** 0..1 -> "74%" */
export const pct0 = (v: number) => `${Math.round(v * 100)}%`;

/** 만원 단위 금액 -> "1,234만" / "-1,895만".
 *  `+ 0` 은 -0 정규화다 — Math.round(-0.3) 은 -0 이고 toLocaleString 이
 *  그것을 "-0" 으로 찍어 «-0만» 이 화면에 나온다. */
export const man = (v: number) => `${int(Math.round(v) + 0)}만`;

/** 만원 단위 금액에 부호를 붙여 손익을 읽히게 한다 */
export const signedMan = (v: number) => `${v > 0 ? "+" : ""}${man(v)}`;

export const months = (v: number) => `${Math.round(v)}개월`;

/** 연 단위 기간 -> "2년" / "2.7년". 서버가 소수 연차(2.651)를 실으므로 그대로
 *  toLocaleString에 넘기면 "2.651년"이 나온다. 정수면 소수점을 뗀다. */
export const yearsLabel = (v: number) => `${Number.isInteger(v) ? v : v.toFixed(1)}년`;

export const meters = (v: number) => `${int(Math.round(v))}m`;

/** 서버 분기 코드 "20261" -> "2026년 1분기". 형식이 다르면 원문을 그대로 둔다 —
 *  못 읽는 값을 그럴듯하게 바꾸는 것이 조용히 거짓이 되는 경로다. */
export const quarter = (v: string): string => {
  const m = /^(\d{4})([1-4])$/.exec(v.trim());
  return m ? `${m[1]}년 ${m[2]}분기` : v;
};

/** §0 원칙 2 — 숫자보다 문장 먼저. 값은 API 실측치에서만 파생된다. */
export const survivalSentence = (survival: number) =>
  `100곳 중 ${Math.round(survival * 100)}곳이 3년을 버텼어요`;

/** 지표를 수치와 단위로 가른다: "53.5만 건" -> ["53.5", "만 건"]. 수치를 크게
 *  찍어 자릿수가 먼저 읽히게 하려는 것이다.
 *
 *  뒷부분에 숫자가 또 있으면 단위가 아니라 문장이므로("77% vs 28%") 통째로
 *  돌려준다. 쪼개면 "77" 만 커지고 뒤 절반이 각주처럼 눌린다. */
export const splitUnit = (v: string): [string, string] => {
  const m = /^([\d,.]+)(.*)$/.exec(v.trim());
  if (!m || /\d/.test(m[2])) return [v, ""];
  return [m[1], m[2]];
};

/** 서버 업태 키의 화면 표기 교정(까페→카페). 값(API 키·비교 대상)은 절대
 *  바꾸지 않는다 — DB 키는 «까페»이고, 이 함수는 렌더 직전에만 쓴다. */
export const uptaeLabel = (u: string) => u.replace("까페", "카페");

/** Station name plus distance when measured; the name alone otherwise. */
export const stationAnchor = (a: StationAnchor): string =>
  a.distanceM === null ? a.name : `${a.name} ${meters(a.distanceM)}`;
