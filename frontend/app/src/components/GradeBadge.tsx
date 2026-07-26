import type { Grade } from "../api/types";
import { gradeColor, gradeLabel } from "../lib/grade";
import s from "./GradeBadge.module.css";

// Fixed format "n등급 (상위 n×10%)" — ui-spec §4/§7. Letter grades (A+) and
// scores (92점) are banned pseudo-precision; the decile is all we validated.
// The badge carries the same 10-step ramp as the map so a card and its cell
// read as the same object.
export default function GradeBadge({ grade, size = "md" }: { grade: Grade; size?: "md" | "lg" }) {
  return (
    <span
      className={size === "lg" ? s.badgeLg : s.badge}
      style={{ background: gradeColor(grade), color: grade <= 5 ? "#FFFFFF" : "var(--color-ink-700)" }}
    >
      {gradeLabel(grade)}
    </span>
  );
}
