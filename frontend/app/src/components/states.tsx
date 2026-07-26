// Shared explicit states — the no-mock policy makes these first-class UI.
// Copy is fixed by ui-spec.md §7; do not improvise alternates per screen.

export function Loading() {
  return <p role="status">불러오는 중…</p>;
}

export function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert">
      <p>데이터를 불러오지 못했습니다 — 다시 시도</p>
      <button onClick={onRetry}>다시 시도</button>
    </div>
  );
}

export function Empty() {
  return <p>조건에 맞는 격자가 없습니다. 범위를 넓혀보세요.</p>;
}
