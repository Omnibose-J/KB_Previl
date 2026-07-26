import type { Grade } from "../api/types";

// Grade presentation. The decile is the only unit we validated (ui-spec §4):
// no letter grades, no 0-100 scores, no continuous alpha ramp.

/** Fixed badge format — "1등급 (상위 10%)". */
export const gradeLabel = (grade: Grade) => `${grade}등급 (상위 ${grade * 10}%)`;

/** 10-step discrete ramp, grade 1 = darkest. Tokens, not literals (§4). */
export const gradeColor = (grade: Grade) => `var(--color-heatmap-${grade})`;

/** Cells with no observable value are hatched in this neutral, never coloured 0. */
export const NULL_COLOR = "var(--color-heatmap-null)";

/** Legend labels every other step — 10 labels are unreadable (ui-spec §3-S3). */
export const LEGEND_STEPS: Grade[] = [1, 3, 5, 7, 10];

export const isGrade = (n: number): n is Grade => Number.isInteger(n) && n >= 1 && n <= 10;
