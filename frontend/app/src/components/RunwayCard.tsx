import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunwayInput, RunwayResponse } from "../api/types";
import { man, pct0, signedMan } from "../lib/format";
import { ErrorState, Loading } from "./states";
import s from "./RunwayCard.module.css";

// S4 money-tab centrepiece: «내 예산으로 이 자리에서 몇 개월 버티나». Revenue
// ramps up while rent runs in full from month one — the chart shows the
// remaining-money valley and where (if anywhere) it crosses zero.
//
// Two rules carried over from the card this one replaced:
//   1. A defaulted revenue is always captioned with where it came from.
//   2. Numbers come from POST /runway only. No arithmetic on this side.

const DEBOUNCE_MS = 400;

const RAMP_PRESETS: { value: 3 | 6 | 9; label: string; hint: string }[] = [
  { value: 3, label: "빨리", hint: "3달" },
  { value: 6, label: "보통", hint: "6달" },
  { value: 9, label: "천천히", hint: "9달" },
];

export default function RunwayCard({
  gridId,
  uptae,
  budget,
  rentMonthly,
  upfront,
  onBudgetChange,
}: {
  gridId: string;
  uptae: string;
  budget: number | null;
  rentMonthly: number | null;
  upfront: number | null;
  onBudgetChange: (patch: {
    budget?: number | null;
    rentMonthly?: number | null;
    upfront?: number | null;
  }) => void;
}) {
  const [revenue, setRevenue] = useState<number | null>(null);
  const [margin, setMargin] = useState<number | null>(null);
  const [ramp, setRamp] = useState<3 | 6 | 9>(6);
  const [debounced, setDebounced] = useState<RunwayInput | null>(null);

  const ready = budget !== null && upfront !== null && rentMonthly !== null;

  useEffect(() => {
    if (!ready) {
      setDebounced(null);
      return;
    }
    const input: RunwayInput = {
      gridId,
      uptae,
      budget: budget!,
      upfront: upfront!,
      rentMonthly: rentMonthly!,
      rampMonths: ramp,
      ...(revenue !== null ? { revenueMonthly: revenue } : {}),
      ...(margin !== null ? { margin } : {}),
    };
    const t = setTimeout(() => setDebounced(input), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [ready, gridId, uptae, budget, upfront, rentMonthly, revenue, margin, ramp]);

  const q = useQuery({
    queryKey: ["runway", debounced],
    queryFn: () => api.runway(debounced!),
    enabled: debounced !== null,
  });

  return (
    <section className={s.card}>
      <header className={s.head}>
        <h2 className={s.title}>이 예산으로, 여기서 버틸 수 있을까요?</h2>
        <p className={s.lead}>
          처음 몇 달은 매출이 낮은데 월세는 다 나가요. 그 골짜기를 넘을 돈이
          있는지 봐요.
        </p>
      </header>

      <div className={s.inputs}>
        <Field
          label="총 예산"
          value={budget}
          onChange={(v) => onBudgetChange({ budget: v })}
          placeholder="예: 15,000"
          required
        />
        <Field
          label="초기투자 총액"
          value={upfront}
          onChange={(v) => onBudgetChange({ upfront: v })}
          placeholder="예: 8,000"
          required
        />
        <Field
          label="월 임대료"
          value={rentMonthly}
          onChange={(v) => onBudgetChange({ rentMonthly: v })}
          placeholder="예: 250"
          required
        />
        <Field label="월 예상매출" value={revenue} onChange={setRevenue} placeholder="비워두면 주변 평균" />
        <Field
          label="마진율"
          value={margin === null ? null : Math.round(margin * 100)}
          onChange={(v) => setMargin(v === null ? null : v / 100)}
          unit="%"
          placeholder="비워두면 기본값"
        />
        <div className={s.field}>
          <span className={s.fieldLabel}>매출이 자리 잡는 속도</span>
          <div className={s.presets} role="radiogroup" aria-label="매출이 자리 잡는 속도">
            {RAMP_PRESETS.map((p) => (
              <button
                key={p.value}
                role="radio"
                aria-checked={ramp === p.value}
                className={ramp === p.value ? s.presetOn : s.preset}
                onClick={() => setRamp(p.value)}
              >
                {p.label} <i>{p.hint}</i>
              </button>
            ))}
          </div>
        </div>
      </div>

      {!ready ? (
        <p className={s.prompt}>총 예산·초기투자·월 임대료를 넣으면 계산해 드려요.</p>
      ) : q.isPending ? (
        <Loading label="계산 중…" />
      ) : q.isError ? (
        <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} />
      ) : (
        <Verdict data={q.data} />
      )}
    </section>
  );
}

function Verdict({ data }: { data: RunwayResponse }) {
  const headline = HEADLINES[data.level](data);
  return (
    <>
      <div className={`${s.verdict} ${s[LEVEL_CLASS[data.level]]}`}>
        <strong>{headline.title}</strong>
        <span>{headline.sub}</span>
      </div>

      {data.level !== "IMPOSSIBLE" ? (
        <>
          <div className={s.results}>
            <Stat
              label="계약하고 남는 돈"
              value={man(data.reserve)}
              note="총 예산에서 초기투자를 뺀 돈이에요"
            />
            <Stat
              label="골짜기의 깊이"
              value={data.workingCapitalNeed > 0 ? man(data.workingCapitalNeed) : "없음"}
              note={
                data.workingCapitalNeed > 0
                  ? `개업 ${data.troughMonth}개월차가 가장 깊어요`
                  : "첫 달부터 벌어서 버틸 돈이 필요 없어요"
              }
            />
            <Stat
              label="월 흑자 전환"
              value={data.breakevenMonth !== null ? `${data.breakevenMonth}개월차` : "없음"}
              note={
                data.breakevenMonth !== null
                  ? "이 달부터 한 달 장사가 남아요"
                  : `${data.horizonMonths}개월 안에는 안 와요 — 조건을 다시 봐야 해요`
              }
            />
          </div>

          <RunwayChart data={data} />
        </>
      ) : null}

      {data.revenueSource !== "user_input" ? (
        <p className={s.caption}>
          {data.revenueSource === "trade_area_average"
            ? "이 주변 상권의 같은 업종 평균 매출로 계산했어요. 이 가게의 추정 매출이 아니에요."
            : "서울 상권 평균 매출로 계산했어요. 이 자리의 추정 매출이 아니에요."}
        </p>
      ) : null}
      <p className={s.assumptions}>
        {data.assumptions
          .map((a) => `${a.label} ${a.value <= 1 ? pct0(a.value) : man(a.value)} (${a.source})`)
          .join(" · ")}
      </p>
    </>
  );
}

const LEVEL_CLASS: Record<RunwayResponse["level"], string> = {
  IMPOSSIBLE: "vRed",
  DANGER: "vRed",
  WARN: "vOrange",
  OK: "vGreen",
};

const HEADLINES: Record<
  RunwayResponse["level"],
  (d: RunwayResponse) => { title: string; sub: string }
> = {
  IMPOSSIBLE: (d) => ({
    title: "이 예산으로는 계약 자체가 어려워요",
    sub: `초기투자가 예산보다 ${man(-d.reserve)} 많아요.`,
  }),
  DANGER: (d) => ({
    title:
      d.depletionMonth !== null
        ? `개업 ${d.depletionMonth}개월차에 돈이 바닥나요`
        : "지금 여유자금으로는 초기 골짜기를 못 넘어요",
    sub:
      d.breakevenMonth !== null
        ? `월 흑자는 ${d.breakevenMonth}개월차부터라, 그 전에 버틸 돈이 모자라요.`
        : `${d.horizonMonths}개월 안에 월 흑자가 안 와요. 매출·임대료 조건을 다시 봐야 해요.`,
  }),
  WARN: () => ({
    title: "버티긴 하는데, 여유가 거의 없어요",
    sub: "매출이 예상보다 늦게 오르면 위험해요. 아래 속도를 «천천히»로 바꿔서 확인해 보세요.",
  }),
  OK: () => ({
    title: "초기 골짜기를 넘을 돈이 확보돼요",
    sub: "예상보다 매출이 늦게 올라도 버틸 여유가 있어요.",
  }),
};

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className={s.result}>
      <span className={s.resultLabel}>{label}</span>
      <strong className={s.resultValue}>{value}</strong>
      <span className={s.resultNote}>{note}</span>
    </div>
  );
}

// ---- chart ----------------------------------------------------------------
// One series: 남은 돈(t) = reserve + cum(t), anchored at t=0 (계약 직후), with
// a dashed zero line. The zero crossing IS the story — mark it and little else.
// Static SVG + sr-only table, same idiom as SurvivalTrend.

const W = 680;
const H = 210;
const PAD = { top: 26, right: 24, bottom: 30, left: 12 };

function RunwayChart({ data }: { data: RunwayResponse }) {
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

  // Keep point labels inside the plot: clamp the anchor near either edge and
  // flip above the dot when below would collide with the month axis.
  const labelPos = (month: number, balance: number) => {
    const px = x(month);
    const py = y(balance);
    const anchor = px < PAD.left + 80 ? "start" : px > W - PAD.right - 80 ? "end" : "middle";
    const below = py + 22 <= H - PAD.bottom;
    return { lx: px, ly: below ? py + 20 : py - 12, anchor } as const;
  };

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
        {dry !== null ? (
          <g>
            <circle className={s.dotBad} cx={x(dry.month)} cy={y(dry.balance)} r={5} />
            {(() => {
              const p = labelPos(dry.month, dry.balance);
              return (
                <text className={s.markBad} x={p.lx} y={p.ly} textAnchor={p.anchor}>
                  {dry.month}개월차에 바닥
                </text>
              );
            })()}
          </g>
        ) : (
          <g>
            <circle className={s.dot} cx={x(trough.month)} cy={y(trough.balance)} r={5} />
            {(() => {
              const p = labelPos(trough.month, trough.balance);
              return (
                <text className={s.mark} x={p.lx} y={p.ly} textAnchor={p.anchor}>
                  가장 얕을 때 {man(trough.balance)}
                </text>
              );
            })()}
          </g>
        )}

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

function Field({
  label,
  value,
  onChange,
  unit = "만원",
  placeholder,
  required,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  unit?: string;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className={s.field}>
      <span className={s.fieldLabel}>
        {label}
        {required ? <i className={s.req}>필수</i> : null}
      </span>
      <span className={s.fieldInput}>
        <input
          type="number"
          min={0}
          value={value ?? ""}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        />
        <span className={s.unit}>{unit}</span>
      </span>
    </label>
  );
}
