import type { ReactNode } from "react";
import s from "./Nav.module.css";
import markUrl from "../assets/previl-mark.png";

// Shared compact top bar for S2/S3 (figma-snapshot Nav, 64~70px). S1 renders its
// own taller landing nav. `center` carries either the step indicator (S2) or the
// condition summary pill (S3).
//
// 로고 블록은 S1 랜딩 nav 와 같은 것을 쓴다 — 마크 이미지 26px, 워드마크 19px,
// «KB» 만 브랜드 옐로. 예전에는 여기만 문자 «P» 를 넣은 노란 타일이라, 랜딩에서
// 넘어오는 순간 다른 서비스처럼 보였다.

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
      <button className={s.logo} onClick={onHome} aria-label="처음으로">
        <img className={s.mark} src={markUrl} alt="" />
        <span className={s.wordmark}>
          <span className={s.wordmarkKb}>KB</span> Previl
        </span>
      </button>
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
