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
  // 축은 데이터 범위에 맞춘다 — 항상 0 을 포함시키면 잔고가 0 에서 먼 경우
  // 곡선이 위에 눌려 경사가 안 보인다(2026-08-03 사용자 보고). 0 선은 데이터
  // 범위(여백 포함)에 들어올 때만 그린다 — 바닥 근처거나 실제로 뚫린 경우.
  const dataLo = Math.min(...values);
  const dataHi = Math.max(...values);
  const dataSpan = dataHi - dataLo || Math.abs(dataHi) || 1;
  const margin = dataSpan * 0.12;
  const zeroVisible = dataLo - margin <= 0;
  const lo = zeroVisible ? Math.min(0, dataLo - margin) : dataLo - margin;
  const hi = dataHi + margin;
  const span = hi - lo || 1;

  const x = (month: number) =>
    PAD.left + (month / data.horizonMonths) * (W - PAD.left - PAD.right);
  const y = (v: number) =>
    PAD.top + (1 - (v - lo) / span) * (H - PAD.top - PAD.bottom);

  const path = balances
    .map((b, i) => `${i === 0 ? "M" : "L"}${x(b.month).toFixed(1)} ${y(b.balance).toFixed(1)}`)
    .join(" ");
  // 선 아래를 칠해 «남아 있는 돈의 부피»로 읽히게 한다. 0 선이 보일 때는 거기
  // 까지 채우고 위/아래를 클립으로 갈라 위는 잉크 워시, 아래(바닥난 구간)는
  // 빨강. 0 선이 화면 밖(한참 아래)이면 플롯 바닥까지 워시만 채운다.
  const areaBase = zeroVisible ? y(0) : H - PAD.bottom;
  const area =
    `${path} L${x(balances[balances.length - 1].month).toFixed(1)} ${areaBase.toFixed(1)}` +
    ` L${x(0).toFixed(1)} ${areaBase.toFixed(1)} Z`;

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
            ? `남은 돈 곡선. 개업 ${dry.month}개월차에 0 아래로 내려가요`
            : `남은 돈 곡선. ${data.horizonMonths}개월 동안 0 아래로 내려가지 않아요`
        }
      >
        {zeroVisible ? (
          <>
            <defs>
              <clipPath id="rw-above">
                <rect x={0} y={0} width={W} height={y(0)} />
              </clipPath>
              <clipPath id="rw-below">
                <rect x={0} y={y(0)} width={W} height={H - y(0)} />
              </clipPath>
            </defs>
            <path className={s.area} d={area} clipPath="url(#rw-above)" />
            <path className={s.areaBad} d={area} clipPath="url(#rw-below)" />
            <line className={s.zero} x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} />
            <text className={s.zeroLabel} x={W - PAD.right} y={y(0) - 6} textAnchor="end">
              잔고 0
            </text>
          </>
        ) : (
          <path className={s.area} d={area} />
        )}

        <path className={s.line} d={path} />

        {/* 시작점 — 곡선이 어디서 출발하는지(계약하고 남은 돈)를 못박는다.
            최저점이 곧 시작점이면(단조 상승 곡선) 아래 최저점 라벨과 같은 자리에
            겹치므로 생략한다. */}
        {mark.month !== 0 ? (
          <>
            <circle className={s.dot} cx={x(0)} cy={y(data.reserve)} r={4} />
            <text className={s.mark} x={x(0) + 8} y={y(data.reserve) - 10} textAnchor="start">
              시작 {man(data.reserve)}
            </text>
          </>
        ) : null}

        {/* 골짜기 최저점 — 바닥나는 달이 따로 있으면 그 점을 우선한다.
            일반 최저점이 끝점과 같은 달이면(단조 하락) 끝 라벨과 같은 자리라
            생략한다 — 값도 같아서 잃는 정보가 없다. */}
        {dry !== null || mark.month !== last.month ? (
          <>
            <circle
              className={dry ? s.dotBad : s.dot}
              cx={x(mark.month)}
              cy={y(mark.balance)}
              r={5}
            />
            <text className={dry ? s.markBad : s.mark} x={markAt.lx} y={markAt.ly} textAnchor={markAt.anchor}>
              {dry ? `${mark.month}개월차에 바닥` : `가장 얕을 때 ${man(mark.balance)}`}
            </text>
          </>
        ) : null}

        {/* 끝점 — 바닥나는 달이 마침 끝 달이면 바닥 라벨이 우선한다 */}
        {dry === null || dry.month !== last.month ? (
          <text className={s.mark} x={x(last.month) - 4} y={y(last.balance) - 10} textAnchor="end">
            {data.horizonMonths}개월 뒤 {signedMan(last.balance)}
          </text>
        ) : null}

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
        계약하고 남은 돈이 다달이 어떻게 움직이는지예요.{" "}
        {zeroVisible
          ? "점선(잔고 0) 아래 빨갛게 칠해진 구간은 돈이 바닥나 있다는 뜻이에요."
          : "잔고가 0에서 멀어서, 움직임이 잘 보이게 구간을 확대해 그렸어요."}
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
