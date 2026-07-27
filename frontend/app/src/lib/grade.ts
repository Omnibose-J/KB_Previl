import type { Grade } from "../api/types";

// Grade presentation. The decile is the only unit we validated (ui-spec §4):
// no letter grades, no 0-100 scores, no continuous alpha ramp.

/** Fixed badge format — "1등급". "상위 n%" is BANNED (serving-design §3):
 *  grade boundaries are absolute holdout deciles, not a slice of the current
 *  grids, so the percentile translation is simply not true. */
export const gradeLabel = (grade: Grade) => `${grade}등급`;

/** Legend labels every other step — 10 labels are unreadable (ui-spec §3-S3). */
export const LEGEND_STEPS: Grade[] = [1, 3, 5, 7, 10];

/** Recommendation bar (owner call 2026-07-27): a spot is only RECOMMENDED at
 *  grade 1 — the server pads small scopes with grade-2 cells to fill the page
 *  (7/25 districts for 한식), and padding with weaker spots is how "추천" stops
 *  meaning anything. The grade is the server-validated unit, so this is a cut
 *  on served data, not a client-invented score threshold (§3-S3). Non-passing
 *  cells stay reachable through the map as 진단 entries. */
export const isRecommendable = (c: { grade: Grade }) => c.grade === 1;
