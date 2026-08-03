// Input hygiene at the trust boundary (user keyboard → app state → API).
// Two jobs only:
//   1. numbers — reject NaN/Infinity (type=number still lets "1e999" through)
//      and clamp into a sane range, so one stray digit cannot become a
//      조-단위 예산이 되어 서버 유한성 검증까지 흘러가지 않는다.
//   2. text — strip control characters and angle brackets, cap the length,
//      before the value is stored or sent anywhere.

/** 만원 단위 금액 상한(1,000억). 서울 상가 계약에서 나올 수 없는 크기부터는
 *  입력 실수로 본다 — 서버 검증과 별개로 화면이 먼저 거른다. */
export const MAX_MONEY = 10_000_000;

/** type=number 입력값 파싱: 빈 칸·비유한값 → null, 범위 밖 → 경계로 클램프. */
export function parseNum(
  raw: string,
  { min = 0, max = MAX_MONEY }: { min?: number; max?: number } = {},
): number | null {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  if (!Number.isFinite(n)) return null;
  return Math.min(max, Math.max(min, n));
}

/** 자유 텍스트 입력: 제어문자·꺾쇠 제거 + 길이 제한. React 가 출력을 이스케이프
 *  하지만, 서버로 가는 값과 저장되는 값 자체를 깨끗하게 유지한다. */
export function cleanText(raw: string, maxLen = 40): string {
  // eslint-disable-next-line no-control-regex
  return raw.replace(/[<>\x00-\x1f\x7f]/g, "").slice(0, maxLen);
}
