import type { Grade } from "../api/types";

// Grade presentation. The grade is the only unit we validated (ui-spec §4):
// no letter grades, no 0-100 scores, no continuous alpha ramp.

/** Fixed badge format — "1등급". "상위 n%" is BANNED (serving-design §3):
 *  grade boundaries are absolute holdout cuts, not a slice of the current
 *  grids, so the percentile translation is simply not true. */
export const gradeLabel = (grade: Grade) => `${grade}등급`;

/** Legend labels every other step — 10 labels are unreadable (ui-spec §3-S3). */
export const LEGEND_STEPS: Grade[] = [1, 3, 5, 7, 9];

/** Recommendation bar (owner call 2026-07-27, widened 2026-07-31 for 9등급).
 *
 *  This is not a badge filter — S3Results DROPS non-passing cells from the list
 *  (S3Results.tsx), so the bar decides whether a scope shows anything at all.
 *
 *  Grade 1 alone was right while grades were equal deciles (10% of cells). The
 *  내신형 9등급 move cut it to 4.5%, and measured per 자치구 that leaves 7 of 28
 *  scopes with ZERO grade-1 cells for 한식 (5 for 까페, 3 for 일식) and 21 of 28
 *  unable to fill the 20-card page. An empty results screen for a whole 자치구
 *  is worse than a slightly wider bar.
 *
 *  Grades 1-2 cut the empty scopes to 3/28, and those three stay empty even at
 *  grade 3 — they genuinely have no strong cell, so showing nothing there is
 *  the honest answer, not a bug. Grade 3 buys nothing further (3/28 either way)
 *  while admitting the 70.1% band, so the bar stops at 2.
 *
 *  The cost is real and should not be dressed up: grade 2 measures 72.7%, below
 *  the 76.8% the old decile grade 1 did, so the badge promises a little less
 *  than it used to. The better design is to keep the bar at grade 1 and render
 *  the rest as unbadged 진단 cards instead of dropping them — that is a new card
 *  state, not a one-line change, and it is not being built before the deadline.
 *
 *  The grade is the server-validated unit, so this is a cut on served data, not
 *  a client-invented score threshold (§3-S3). */
export const isRecommendable = (c: { grade: Grade }) => c.grade <= 2;
