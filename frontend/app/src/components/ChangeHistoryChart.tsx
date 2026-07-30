import type { ChangeHistory } from "../api/types";
import s from "./ChangeHistoryChart.module.css";

// 주변 300m 에서 열고 닫은 가게. 위로 열었고 아래로 닫았다 — 쌓지 않는다.
// 둘은 부분과 전체가 아니라 서로 반대 방향의 흐름이라, 쌓으면 «합계» 라는
// 있지도 않은 양이 생긴다. 축을 가운데 두면 늘어나는 동네와 줄어드는 동네가
// 한눈에 갈린다.
//
// 6개월 · 3x3 링은 실측으로 정한 값이다. 단일 100m 칸은 어느 단위로 묶어도
// 구간의 대부분이 비고(6개월도 75% 가 빔), 3x3 링 + 6개월이면 20구간 중 19개가
// 채워진다. 화면에서 임의로 바꾸지 말 것 — 서버 계약과 함께 움직여야 한다.

const H = 96;          // 차트 높이(px). 위아래 각 H/2
const GAP = 2;

export default function ChangeHistoryChart({ history }: { history: ChangeHistory }) {
  const { buckets, runs, unit } = history;
  if (buckets.length === 0) return null;

  const peak = Math.max(1, ...buckets.map((b) => Math.max(b.opened, b.closed)));
  const w = 100 / buckets.length;
  const totalOpened = buckets.reduce((n, b) => n + b.opened, 0);
  const totalClosed = buckets.reduce((n, b) => n + b.closed, 0);

  // 구간 시작연도로 눈금을 만든다. 20개 라벨은 겹치므로 2년마다만 보인다.
  const ticks = buckets
    .map((b, i) => ({ i, year: b.from.slice(0, 4), first: b.from.endsWith("-01") }))
    .filter((t) => t.first && Number(t.year) % 2 === 0);

  // 그리는 구간 밖의 재산정은 표시할 자리가 없다. 목록에 있다고 문구를 내보내면
  // 화면에 없는 세로선을 설명하게 되므로, 실제로 그린 것만 세어 문구를 정한다.
  const marks = runs
    .map((r) => {
      const i = buckets.findIndex((b) => b.from <= r.asOf && r.asOf <= b.to);
      return i < 0 ? null : { asOf: r.asOf, x: (i + 1) * w };   // 그 구간의 오른쪽 끝
    })
    .filter((m): m is { asOf: string; x: number } => m !== null);

  return (
    <div className={s.wrap}>
      <div className={s.head}>
        <span className={s.title}>주변에서 열고 닫은 가게</span>
        <span className={s.legend}>
          <em className={s.dotOpen} /> 열었어요 {totalOpened}
          <em className={s.dotClose} /> 닫았어요 {totalClosed}
        </span>
      </div>

      <div className={s.plot} style={{ height: H }} aria-hidden="true">
        <div className={s.axis} />
        {marks.map((m) => (
          // 마지막 구간의 재산정은 선이 플롯 오른쪽 끝에 서므로, 라벨을 그대로
          // 두면 잘린다. 가장자리에서는 안쪽으로 붙인다.
          <span
            key={m.asOf}
            className={m.x > 85 ? `${s.run} ${s.runEnd}` : s.run}
            style={{ left: `${m.x}%` }}
          >
            <em>{m.asOf.slice(2)}</em>
          </span>
        ))}
        {buckets.map((b, i) => (
          <div key={b.from} className={s.col} style={{ left: `${i * w}%`, width: `${w}%` }}>
            <span
              className={s.up}
              style={{ height: `${(b.opened / peak) * (H / 2 - GAP)}px` }}
            />
            <span
              className={s.down}
              style={{ height: `${(b.closed / peak) * (H / 2 - GAP)}px` }}
            />
          </div>
        ))}
      </div>

      <div className={s.ticks} aria-hidden="true">
        {ticks.map((t) => (
          <span key={t.year} className={s.tick} style={{ left: `${t.i * w}%` }}>
            {t.year}
          </span>
        ))}
      </div>

      {/* 표로도 읽히게 둔다 — 막대는 aria-hidden 이라 이게 유일한 접근 경로다. */}
      <table className={s.sr}>
        <caption>{`${unit} · 6개월 단위 개·폐업`}</caption>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.from}>
              <th scope="row">{`${b.from} ~ ${b.to}`}</th>
              <td>{`열었어요 ${b.opened}`}</td>
              <td>{`닫았어요 ${b.closed}`}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className={s.note}>
        이 자리와 맞닿은 {unit} 기준이에요. 같은 범위 안 다른 자리도 같게 나와요.
        {marks.length ? " 세로선은 저희가 등급을 다시 매긴 때예요." : ""}
      </p>
    </div>
  );
}
