import s from "./states.module.css";

// Shared explicit states — the no-mock policy makes these first-class UI.
// Copy is fixed by ui-spec.md §7; do not improvise alternates per screen.
// An error here is the CORRECT rendering when the backend is down: nothing on
// this screen may fall back to a cached, average, or invented number.

export function Loading({ label = "불러오는 중…" }: { label?: string }) {
  return (
    <p className={s.loading} role="status">
      {label}
    </p>
  );
}

export function ErrorState({ onRetry, detail }: { onRetry: () => void; detail?: string }) {
  return (
    <div className={s.error} role="alert">
      <p className={s.errorTitle}>데이터를 불러오지 못했습니다 — 다시 시도</p>
      {detail ? <p className={s.errorDetail}>{detail}</p> : null}
      <button className={s.retry} onClick={onRetry}>
        다시 시도
      </button>
    </div>
  );
}

export function Empty() {
  return <p className={s.empty}>조건에 맞는 격자가 없습니다. 범위를 넓혀보세요.</p>;
}
