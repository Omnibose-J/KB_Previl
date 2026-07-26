import type { Screen } from "../App";
import CaveatStrip from "../components/CaveatStrip";

// S2 조건 입력 — spec: ui-spec.md §3-S2 (P0).
// Required inputs: 업종(from meta().uptae, labels verbatim) + 범위(자치구 다중선택).
// 예산(임대료·초기투자) lives in a collapsed section. 매출·마진·면적 are NOT here
// (they are inline inputs on S4). Funnel numbers must come from the API.
export default function S2Input({ go }: { go: (s: Screen) => void }) {
  return (
    <main>
      {/* TODO(C): 업종 칩(meta) + 자치구 다중선택 + 접힘 예산 + 요약 패널 */}
      <button onClick={() => go({ name: "results" })}>분석 시작</button>
      <CaveatStrip />
    </main>
  );
}
