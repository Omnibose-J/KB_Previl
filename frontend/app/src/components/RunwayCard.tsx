import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunwayInput, RunwayResponse } from "../api/types";
import { man, pct0, quarter } from "../lib/format";
import NumField from "./NumField";
import RunwayChart from "./RunwayChart";
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
  onResult,
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
  /** 계산 결과를 위로 알린다 — 아래 KB 연계 카드(자금 계획)가 부족액을
   *  이 응답(need·reserve)에서 셈한다. 입력이 빠지면 null 로 되돌린다. */
  onResult?: (r: RunwayResponse | null) => void;
}) {
  const [revenue, setRevenue] = useState<number | null>(null);
  const [margin, setMargin] = useState<number | null>(null);
  const [ramp, setRamp] = useState<3 | 6 | 9>(6);
  const [debounced, setDebounced] = useState<RunwayInput | null>(null);

  const ready = budget !== null && upfront !== null && rentMonthly !== null;

  // 자리가 바뀌면 즉시 비운다 — 디바운스 400ms 동안 이전 격자의 판정이 새
  // 격자 제목 아래 그대로 떠 있는 잔상을 막는다.
  useEffect(() => setDebounced(null), [gridId, uptae]);

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

  const result = q.data ?? null;
  useEffect(() => {
    onResult?.(result);
  }, [onResult, result]);

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
        <NumField
          s={s}
          label="총 예산"
          value={budget}
          onChange={(v) => onBudgetChange({ budget: v })}
          placeholder="예: 15,000"
          required
        />
        <NumField
          s={s}
          label="초기투자 총액"
          value={upfront}
          onChange={(v) => onBudgetChange({ upfront: v })}
          placeholder="예: 8,000"
          required
        />
        <NumField
          s={s}
          label="월 임대료"
          value={rentMonthly}
          onChange={(v) => onBudgetChange({ rentMonthly: v })}
          placeholder="예: 250"
          required
        />
        {/* 서버 계약이 gt=0 — 0 매출·0 마진은 422 가 되므로 화면이 먼저 막는다 */}
        <NumField s={s} label="월 예상매출" value={revenue} onChange={setRevenue} min={1} placeholder="비워두면 주변 평균" />
        <NumField
          s={s}
          label="마진율"
          value={margin === null ? null : Math.round(margin * 100)}
          onChange={(v) => setMargin(v === null ? null : v / 100)}
          unit="%"
          min={1}
          max={100}
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
                  : `${data.horizonMonths}개월 안에는 안 와요. 조건을 다시 봐야 해요`
              }
            />
          </div>

          <RunwayChart data={data} />
        </>
      ) : null}

      {data.revenueSource !== "user_input" ? (
        // 금액·기준 분기까지 적는다 — 사용자가 못 본 숫자로 계산된 판정을
        // 읽게 하지 않는다 (서버가 실어 보내는 값 그대로).
        <p className={s.caption}>
          {data.revenueSource === "trade_area_average"
            ? "이 주변 상권의 같은 업종 평균 매출"
            : "서울 상권 평균 매출"}
          {`(월 ${man(data.revenueMonthly)}`}
          {data.revenueAsOfQuarter ? ` · ${quarter(data.revenueAsOfQuarter)} 기준` : ""}
          {`)로 계산했어요. 이 ${data.revenueSource === "trade_area_average" ? "가게" : "자리"}의 추정 매출이 아니에요.`}
        </p>
      ) : null}
      {/* 근거 문구(source)는 2026-08-03 사용자 지시로 화면에서 뺐다 — 값만 남긴다 */}
      <p className={s.assumptions}>
        {data.assumptions
          .map((a) => `${a.label} ${a.value <= 1 ? pct0(a.value) : man(a.value)}`)
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
  WARN: (d) =>
    // 흑자 전환이 지평 안에 없으면 «골짜기»가 아니라 그냥 내리막이다 — 서버가
    // OK 를 WARN 으로 강등해 보내는 케이스라, 문구도 다른 말을 해야 한다.
    d.breakevenMonth === null
      ? {
          title: "버텨도 매달 적자예요",
          sub: `${d.horizonMonths}개월 안에 월 흑자가 안 와요. 매출·임대료 조건을 다시 봐야 해요.`,
        }
      : {
          title: "버티긴 하는데, 여유가 거의 없어요",
          sub: "매출이 예상보다 늦게 오르면 위험해요. 아래 속도를 «천천히»로 바꿔서 확인해 보세요.",
        },
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


