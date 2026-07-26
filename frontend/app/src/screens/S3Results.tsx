import type { Screen } from "../App";
import CaveatStrip from "../components/CaveatStrip";

// S3 결과 — spec: ui-spec.md §3-S3 (P0: 지도 등급 탭 + 목록).
// Map leads (grid polygons via /grids?bbox, discrete 10-step non-brand ramp,
// NULL pattern per §4); list follows (GradeBadge + observed survival + chips).
// What-if recompute goes through POST /economics — never client-side math.
export default function S3Results({ go }: { go: (s: Screen) => void }) {
  return (
    <main>
      {/* TODO(C): 지도(카카오 JS SDK | MapLibre 폴백) + 랭킹 목록 + What-if 패널 */}
      <button onClick={() => go({ name: "detail", gridId: "TODO", from: "results" })}>
        상세 보기
      </button>
      <CaveatStrip />
    </main>
  );
}
