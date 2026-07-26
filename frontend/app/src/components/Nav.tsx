import type { ReactNode } from "react";
import s from "./Nav.module.css";

// Shared top bar. `dark` is only for the S1 hero, which is the single dark
// surface in the product (ui-spec §0 슬롭 표: three dark sections destroyed
// the hierarchy signal in the mockup).
// The yellow mark on "터" is the one brand accent the bar is allowed —
// KB's own sites reserve yellow for the logotype and nothing else.

export type Step = 1 | 2 | 3;

export default function Nav({
  dark = false,
  step,
  right,
  onHome,
}: {
  dark?: boolean;
  step?: Step;
  right?: ReactNode;
  onHome?: () => void;
}) {
  return (
    <nav className={dark ? s.navDark : s.nav}>
      <button className={s.logo} onClick={onHome} aria-label="처음으로">
        <span className={s.mark}>터</span>
        <span className={s.wordmark}>KB 터 · TEO</span>
      </button>
      {step ? <Steps current={step} dark={dark} /> : null}
      <div className={s.right}>{right}</div>
    </nav>
  );
}

// A-mode only (탐색 플로우). The diagnosis flow skips S2/S3 entirely (§2).
const STEP_LABELS = ["조건 입력", "후보 분석", "결과 확인"] as const;

function Steps({ current, dark }: { current: Step; dark: boolean }) {
  return (
    <ol className={dark ? s.stepsDark : s.steps}>
      {STEP_LABELS.map((label, i) => {
        const n = (i + 1) as Step;
        return (
          <li key={label} className={n === current ? s.stepOn : s.step}>
            <span className={s.stepNum}>{n}</span>
            {label}
          </li>
        );
      })}
    </ol>
  );
}
