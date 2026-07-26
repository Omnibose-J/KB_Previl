import type { Screen } from "../App";

// S4 상세 리포트 — spec: ui-spec.md §3-S4 (P0: 등급 + 경제성 카드 + 한계 카드).
// Shared by both entry modes; `from` only changes the breadcrumb.
// Economics card is the centerpiece (단순 회수 vs 위험반영 회수 vs 3년 기대손익)
// with inline 매출·마진·면적 inputs. /report sentences render only if the call
// succeeds — on failure show the error state, never canned prose.
export default function S4Detail({
  go,
  gridId,
  from,
}: {
  go: (s: Screen) => void;
  gridId: string;
  from: "results" | "diagnosis";
}) {
  return (
    <main>
      {/* TODO(C): 등급 히어로, 경제성 카드(/economics), 근거 리포트(/report), 한계 카드 */}
      <p>
        grid {gridId} ({from})
      </p>
      <button onClick={() => go({ name: from === "results" ? "results" : "landing" })}>
        ← 돌아가기
      </button>
    </main>
  );
}
