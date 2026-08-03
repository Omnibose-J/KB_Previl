import type { SurvivalYear } from "../api/types";
import s from "./SurvivalTrend.module.css";

// 랜딩 «왜 지금» 섹션의 근거 그래프. 단일 계열이라 범례를 두지 않고(제목이
// 계열을 지목한다) 값은 정점과 끝점만 직접 적는다 — 점마다 숫자를 붙이면
// 읽히지 않는다. 표본 수까지 필요한 사람을 위해 같은 값을 표로도 낸다.

const W = 680;
const H = 190;
const PAD = { top: 22, right: 66, bottom: 28, left: 10 };

// y축을 0부터 그리지 않는다. 12.7%p 차이를 0~100 축에 올리면 거의 평평한
// 선이 되어 «변화가 없다»는 반대 사실을 말하게 된다. 대신 눈금을 찍어 축이
// 잘려 있음을 드러낸다.
const Y_MIN = 55;
const Y_MAX = 75;
const GRID = [60, 70];

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

export default function SurvivalTrend({ data }: { data: SurvivalYear[] }) {
  if (data.length < 2) return null;

  const x = (i: number) =>
    PAD.left + (i / (data.length - 1)) * (W - PAD.left - PAD.right);
  const y = (survival: number) => {
    const t = (survival * 100 - Y_MIN) / (Y_MAX - Y_MIN);
    return PAD.top + (1 - t) * (H - PAD.top - PAD.bottom);
  };

  const path = data
    .map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(d.survival).toFixed(1)}`)
    .join(" ");

  const peak = data.reduce((best, d, i) => (d.survival > data[best].survival ? i : best), 0);
  const last = data.length - 1;
  const marked = [peak, last];

  return (
    <figure className={s.fig}>
      <svg
        className={s.svg}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={
          `서울 음식점 3년 생존율. ${data[peak].year}년 개업 ${pct(data[peak].survival)}에서 ` +
          `${data[last].year}년 개업 ${pct(data[last].survival)}로 내려왔어요`
        }
      >
        {GRID.map((g) => (
          <g key={g}>
            <line
              className={s.grid}
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(g / 100)}
              y2={y(g / 100)}
            />
            <text className={s.tick} x={W - PAD.right + 8} y={y(g / 100) + 4}>
              {g}%
            </text>
          </g>
        ))}

        <path className={s.line} d={path} pathLength={1} />

        {marked.map((i) => (
          <circle key={i} className={s.dot} cx={x(i)} cy={y(data[i].survival)} r={5} />
        ))}

        {/* 정점은 위로, 끝점은 아래로. 끝점을 같은 높이에 두면 60% 눈금과
            9px 안에서 부딪힌다 — 값과 축이 한 덩어리로 읽힌다. */}
        <text className={s.value} x={x(peak)} y={y(data[peak].survival) - 12} textAnchor="middle">
          {pct(data[peak].survival)}
        </text>
        <text
          className={s.value}
          x={x(last) + 8}
          y={y(data[last].survival) + 20}
          textAnchor="end"
        >
          {pct(data[last].survival)}
        </text>

        <text className={s.axis} x={x(0)} y={H - 8}>
          {data[0].year}
        </text>
        <text className={s.axis} x={x(peak)} y={H - 8} textAnchor="middle">
          {data[peak].year}
        </text>
        <text className={s.axis} x={x(last)} y={H - 8} textAnchor="end">
          {data[last].year}
        </text>
      </svg>

      <figcaption className={s.cap}>
        서울에서 문 연 일반음식점이 3년을 넘긴 비율이에요. 3년이 다 지난 개업만
        셌기 때문에 마지막 해는 {data[last].year}년이에요.
      </figcaption>

      <table className={s.srOnly}>
        <caption>개업연도별 3년 생존율</caption>
        <thead>
          <tr>
            <th scope="col">개업연도</th>
            <th scope="col">3년 생존율</th>
            <th scope="col">개업 수</th>
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.year}>
              <th scope="row">{d.year}</th>
              <td>{pct(d.survival)}</td>
              <td>{d.opened.toLocaleString("ko-KR")}곳</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
