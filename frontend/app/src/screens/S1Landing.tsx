import type { Screen } from "../App";

// S1 랜딩 — spec: frontend/design/ui-spec.md §3-S1 (P0).
// Build order: hero + 정직성 스트립 + 기능 카드 3장. Copy comes from the spec's
// replacement table — the Figma snapshot numbers are mock and must not be used.
export default function S1Landing({ go }: { go: (s: Screen) => void }) {
  return (
    <main>
      <h1>KB 터 · TEO</h1>
      {/* TODO(C): hero, 정직성 스트립, 탭 2개(자리 찾기 / 이 자리 어때?) */}
      <button onClick={() => go({ name: "input" })}>자리 찾기</button>
    </main>
  );
}
