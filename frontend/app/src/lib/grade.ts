import type { Grade } from "../api/types";

// Grade presentation. The decile is the only unit we validated (ui-spec §4):
// no letter grades, no 0-100 scores, no continuous alpha ramp.

/** Fixed badge format — "1등급". "상위 n%" is BANNED (serving-design §3):
 *  grade boundaries are absolute holdout deciles, not a slice of the current
 *  grids, so the percentile translation is simply not true. */
export const gradeLabel = (grade: Grade) => `${grade}등급`;

/** Legend labels every other step — 10 labels are unreadable (ui-spec §3-S3). */
export const LEGEND_STEPS: Grade[] = [1, 3, 5, 7, 10];
