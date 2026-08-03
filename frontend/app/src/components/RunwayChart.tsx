import type { RunwayResponse } from "../api/types";
import { man, signedMan } from "../lib/format";
import s from "./RunwayCard.module.css";

// RunwayCard 의 차트 절 — 카드 본체와 같은 CSS 모듈을 쓴다(한 카드의 두 파일).
// One series: 남은 돈(t) = reserve + cum(t), anchored at t=0 (계약 직후), with
// a dashed zero line. The zero crossing IS the story — mark it and little else.
// Static SVG + sr-only table, same idiom as SurvivalTrend.

const W = 680;
const H = 210;
const PAD = { top: 26, right: 24, bottom: 30, left: 12 };

export default function RunwayChart({ data }: { data: RunwayResponse }) {
  const balances = [
    { month: 0, balance: data.reserve },
    ...data.curve.map((p) => ({ month: p.month, balance: data.reserve + p.cum })),
  ];
  const values = balances.map((b) => b.balance);
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const span = hi - lo || 1;

  const x = (month: number) =>
    PAD.left + (month / data.horizonMonths) * (W - PAD.left - PAD.right);
  const y = (v: number) =>
    PAD.top + (1 - (v - lo) / span) * (H - PAD.top - PAD.bottom);

  const path = balances
    .map((b, i) => `${i === 0 ? "M" : "L"}${x(b.month).toFixed(1)} ${y(b.balance).toFixed(1)}`)
    .join(" ");

  const troughIdx = values.indexOf(Math.min(...values));
  const trough = balances[troughIdx];
  const last = balances[balances.length - 1];
  const dry = data.depletionMonth !== null
    ? balances.find((b) => b.month === data.depletionMonth) ?? null
    : null;

  // Keep the point label inside the plot: clamp the anchor near either edge
  // and flip above the dot when below would collide with the month axis.
  const mark = dry ?? trough;
  const px = x(mark.month);
  const py = y(mark.balance);
  const markAt = {
    lx: px,
    ly: py + 22 <= H - PAD.bottom ? py + 20 : py - 12,
    anchor: px < PAD.left + 80 ? "start" : px > W - PAD.right - 80 ? "end" : "middle",
  } as const;

  return (
    <figure className={s.fig}>
      <svg
        className={s.svg}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={
          dry !== null
            ? `남은 돈 곡선 — 개업 ${dry.month}개월차에 0 아래로 내려가요`
            : `남은 돈 곡선 — ${data.horizonMonths}개월 동안 0 아래로 내려가지 않아요`
        }
      >
        <line className={s.zero} x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} />
        <text className={s.zeroLabel} x={W - PAD.right} y={y(0) - 6} textAnchor="end">
          잔고 0
        </text>

        <path className={s.line} d={path} />

        {/* 골짜기 최저점 — 바닥나는 달이 따로 있으면 그 점을 우선한다 */}
        <circle
          className={dry ? s.dotBad : s.dot}
          cx={x(mark.month)}
          cy={y(mark.balance)}
          r={5}
        />
        <text className={dry ? s.markBad : s.mark} x={markAt.lx} y={markAt.ly} textAnchor={markAt.anchor}>
          {dry ? `${mark.month}개월차에 바닥` : `가장 얕을 때 ${man(mark.balance)}`}
        </text>

        <text className={s.mark} x={x(last.month) - 4} y={y(last.balance) - 10} textAnchor="end">
          {data.horizonMonths}개월 뒤 {signedMan(last.balance)}
        </text>

        <text className={s.axis} x={x(0)} y={H - 8}>
          개업
        </text>
        <text className={s.axis} x={x(12)} y={H - 8} textAnchor="middle">
          1년
        </text>
        <text className={s.axis} x={x(24)} y={H - 8} textAnchor="end">
          2년
        </text>
      </svg>
      <figcaption className={s.cap}>
        계약하고 남은 돈이 다달이 어떻게 움직이는지예요. 점선 아래로 내려가면
        그 달에 돈이 바닥난다는 뜻이에요.
      </figcaption>

      <table className={s.srOnly}>
        <caption>개업 후 월별 남은 돈</caption>
        <thead>
          <tr>
            <th scope="col">개월차</th>
            <th scope="col">그 달 손익</th>
            <th scope="col">남은 돈</th>
          </tr>
        </thead>
        <tbody>
          {data.curve.map((p) => (
            <tr key={p.month}>
              <th scope="row">{p.month}</th>
              <td>{signedMan(p.net)}</td>
              <td>{signedMan(data.reserve + p.cum)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
