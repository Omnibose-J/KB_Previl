import s from "./BrandMark.module.css";
import markUrl from "../assets/previl-mark.png";

// 화면마다 따로 그리던 로고 블록. S1·S2·S3·S4 가 같은 것을 쓰지 않으면 넘어가는
// 순간 다른 서비스처럼 보인다 — 실제로 예전에 S2 만 노란 «P» 타일이었다.
//
// onClick 을 주면 버튼, 안 주면 그냥 표시다. 랜딩에서도 버튼으로 두는 편이
// 낫다: 스크롤을 내린 사용자가 로고를 눌러 맨 위로 가는 것은 굳은 관행이다.

export default function BrandMark({ onClick }: { onClick?: () => void }) {
  const inner = (
    <>
      <img className={s.mark} src={markUrl} alt="" />
      <span className={s.wordmark}>
        <span className={s.kb}>KB</span> Previl
      </span>
    </>
  );

  if (!onClick) return <div className={s.brand}>{inner}</div>;
  return (
    <button className={s.brandBtn} onClick={onClick} aria-label="처음으로">
      {inner}
    </button>
  );
}
