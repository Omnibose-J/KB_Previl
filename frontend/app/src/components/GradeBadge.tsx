import type { Grade } from "../api/types";

// Fixed format "n등급 (상위 n×10%)" — ui-spec §4/§7. Letter grades (A+) and
// scores (92점) are banned pseudo-precision; the decile is all we validated.
export default function GradeBadge({ grade }: { grade: Grade }) {
  return (
    <span className="grade-badge" data-grade={grade}>
      {grade}등급 (상위 {grade * 10}%)
    </span>
  );
}
