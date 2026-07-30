import type { Grade } from "../api/types";

// Grade presentation. The grade is the only unit we validated (ui-spec §4):
// no letter grades, no 0-100 scores, no continuous alpha ramp.

/** Fixed badge format — "1등급". "상위 n%" is BANNED (serving-design §3):
 *  grade boundaries are absolute holdout cuts, not a slice of the current
 *  grids, so the percentile translation is simply not true. */
export const gradeLabel = (grade: Grade) => `${grade}등급`;

/** Legend labels every other step — 10 labels are unreadable (ui-spec §3-S3). */
export const LEGEND_STEPS: Grade[] = [1, 3, 5, 7, 10];

/** Recommendation bar (owner call 2026-07-27, widened 2026-07-30): a spot is
 *  RECOMMENDED at grade 1-2. The bar was grade 1 alone while grades were equal
 *  deciles — grade 1 then held 10% of cells, enough to fill a 20-card page in
 *  most scopes (7/25 districts for 한식 already needed grade-2 padding).
 *
 *  Under the normal-shaped grades, grade 1 holds 2.3%. A 자치구 of ~800 cells
 *  yields ~18 of them, so the cap of 20 could no longer be filled ANYWHERE and
 *  nearly every scope would fall back to padding. Grades 1-2 together are 6.7%
 *  — still stricter than the old bar — and both bands measure at or above the
 *  survival the old grade 1 did (80.6% / 76.5% vs 76.8%), so the promise behind
 *  "추천" does not weaken. The grade is the server-validated unit, so this is a
 *  cut on served data, not a client-invented score threshold (§3-S3).
 *  Non-passing cells stay reachable through the map as 진단 entries. */
export const isRecommendable = (c: { grade: Grade }) => c.grade <= 2;
