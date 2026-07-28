// Display formatting. Every function here takes a value that ALREADY came from
// the API — none of them invent, default, or round away a missing value.
// NULL never becomes 0 (ui-spec §4): callers state 정보 없음 instead.

import type { StationAnchor } from "../api/types";

export const int = (v: number) => v.toLocaleString("ko-KR");

/** 0..1 -> "74.3%" */
export const pct1 = (v: number) => `${(v * 100).toFixed(1)}%`;

/** 0..1 -> "74%" */
export const pct0 = (v: number) => `${Math.round(v * 100)}%`;

/** 만원 단위 금액 -> "1,234만" / "-1,895만" */
export const man = (v: number) => `${int(Math.round(v))}만`;

/** 만원 단위 금액에 부호를 붙여 손익을 읽히게 한다 */
export const signedMan = (v: number) => `${v > 0 ? "+" : ""}${man(v)}`;

export const months = (v: number) => `${Math.round(v)}개월`;

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

/** Station name plus distance when measured; the name alone otherwise. */
export const stationAnchor = (a: StationAnchor): string =>
  a.distanceM === null ? a.name : `${a.name} ${meters(a.distanceM)}`;
