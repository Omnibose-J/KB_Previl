import type { ReactNode } from "react";
import BrandMark from "./BrandMark";
import s from "./Nav.module.css";

// Shared top bar for S2/S3. `center` carries either the step indicator (S2) or
// the condition summary pill (S3).
//
// 높이는 --nav-h 하나로 묶는다. 예전에는 패딩으로 잡혀 있어서 가운데 내용이
// 스텝이냐 조건칩이냐에 따라 화면마다 헤더가 들쭉날쭉했다.

export type Step = 1 | 2 | 3;

export default function Nav({
  step,
  center,
  right,
  onHome,
}: {
  step?: Step;
  center?: ReactNode;
  right?: ReactNode;
  onHome?: () => void;
}) {
  return (
    <nav className={s.nav}>
      <BrandMark onClick={onHome} />
      {/* center wins over step: a screen that supplies its own center content
          (S3's condition pill) must not have it silently swallowed. */}
      <div className={s.center}>{center ?? (step ? <Steps current={step} /> : null)}</div>
      <div className={s.right}>{right}</div>
    </nav>
  );
}

// A-mode only (탐색 플로우). The diagnosis flow skips S2/S3 entirely (§2).
const STEP_LABELS = ["조건 입력", "후보 분석", "결과 확인"] as const;

function Steps({ current }: { current: Step }) {
  return (
    <ol className={s.steps}>
      {STEP_LABELS.map((label, i) => {
        const n = (i + 1) as Step;
        return (
          <li key={label} className={n === current ? s.stepOn : s.step}>
            <span className={s.stepNum}>{n}</span>
            <span className={s.stepLabel}>{label}</span>
            {n < 3 ? <i className={s.stepTick} /> : null}
          </li>
        );
      })}
    </ol>
  );
}
