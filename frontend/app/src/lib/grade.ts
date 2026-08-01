import type { Grade } from "../api/types";

// Grade presentation. The grade is the only unit we validated (ui-spec §4):
// no letter grades, no 0-100 scores, no continuous alpha ramp.

/** Fixed badge format — "1등급". "상위 n%" is BANNED (serving-design §3):
 *  grade boundaries are absolute holdout cuts, not a slice of the current
 *  grids, so the percentile translation is simply not true. */
export const gradeLabel = (grade: Grade) => `${grade}등급`;

/** 한 칸 걸러 하나만 적는다. 9개를 다 적으면 안 읽힌다. */
export const LEGEND_STEPS: Grade[] = [1, 3, 5, 7, 9];

/** 추천 문턱. 배지 필터가 아니라 목록 자체를 자른다 — S3 는 통과 못한 칸을 뺀다.
 *
 *  내신형 9등급으로 바꾸며 1등급이 전체의 4.5%가 됐다. 1등급만 남기면 목록이
 *  선다 — 자치구 25곳 중 한식 1등급이 20장 이상인 곳은 7곳뿐이고 18곳은 못
 *  채운다(까페 21곳·일식 15곳 미달). 1~2등급이면 미달이 한식 7·까페 4·일식 1로
 *  줄고, 12업종을 통틀어 1~2등급이 아예 없는 자치구는 5곳(분식 5·기타 1)이다.
 *
 *  대가: 2등급 실측은 72.9%로 옛 등분위 1등급(76.9%)보다 낮다. 더 나은 설계와
 *  왜 지금 안 하는지는 docs/tracking/findings.md F-S1 «Design debt». */
export const isRecommendable = (c: { grade: Grade }) => c.grade <= 2;
