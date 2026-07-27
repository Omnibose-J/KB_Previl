import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { EconomicsInput, Grade } from "../api/types";
import { months, signedMan } from "../lib/format";
import { gradeLabel } from "../lib/grade";
import { ErrorState, Loading } from "./states";
import s from "./EconomicsCard.module.css";

// 경제성 카드 — the centrepiece of S4 (ui-spec §3-S4). 단순 회수 vs 위험반영
// 회수 is the one contrast only we can draw: same revenue, same rent, different
// survival odds, different money left after three years.
//
// Two rules are baked into this component so no screen can forget them (§4):
//   1. the Seoul-average caption whenever the user left 매출 blank;
//   2. every number arrives from POST /economics — the formula is NEVER
//      reimplemented client-side, because two copies always drift apart.

const DEBOUNCE_MS = 400;

export default function EconomicsCard({
  gridId,
  uptae,
  grade,
  rentMonthly,
  upfront,
  onBudgetChange,
}: {
  gridId: string;
  uptae: string;
  grade: Grade;
  rentMonthly: number | null;
  upfront: number | null;
  onBudgetChange: (patch: { rentMonthly?: number | null; upfront?: number | null }) => void;
}) {
  const [revenue, setRevenue] = useState<number | null>(null);
  const [margin, setMargin] = useState<number | null>(null);
  const [debounced, setDebounced] = useState<EconomicsInput | null>(null);

  const ready = rentMonthly !== null && upfront !== null;

  useEffect(() => {
    if (!ready) {
      setDebounced(null);
      return;
    }
    const input: EconomicsInput = {
      gridId,
      uptae,
      rentMonthly: rentMonthly!,
      upfront: upfront!,
      ...(revenue !== null ? { revenueMonthly: revenue } : {}),
      ...(margin !== null ? { margin } : {}),
    };
    const t = setTimeout(() => setDebounced(input), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [ready, gridId, uptae, rentMonthly, upfront, revenue, margin]);

  const q = useQuery({
    queryKey: ["economics", debounced],
    queryFn: () => api.economics(debounced!),
    enabled: debounced !== null,
  });

  return (
    <section className={s.card}>
      <header className={s.head}>
        <h2 className={s.title}>이 자리에 들어가면, 3년 뒤에</h2>
        <p className={s.lead}>같은 조건이라도 자리가 다르면 3년 뒤 결과가 갈립니다.</p>
      </header>

      <div className={s.inputs}>
        <Field
          label="월 임대료"
          value={rentMonthly}
          onChange={(v) => onBudgetChange({ rentMonthly: v })}
          placeholder="예: 250"
          required
        />
        <Field
          label="초기투자 총액"
          value={upfront}
          onChange={(v) => onBudgetChange({ upfront: v })}
          placeholder="예: 8,000"
          required
        />
        <Field label="월 예상매출" value={revenue} onChange={setRevenue} placeholder="비워두면 서울 평균" />
        <Field
          label="마진율"
          value={margin === null ? null : Math.round(margin * 100)}
          onChange={(v) => setMargin(v === null ? null : v / 100)}
          unit="%"
          placeholder="비워두면 기본값"
        />
      </div>

      {!ready ? (
        <p className={s.prompt}>월 임대료와 초기투자를 넣으면 계산합니다.</p>
      ) : q.isPending ? (
        <Loading label="계산 중…" />
      ) : q.isError ? (
        <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} />
      ) : (
        <>
          <div className={s.results}>
            <Result
              label="단순 회수"
              value={q.data.simplePaybackMonths}
              render={months}
              note="문 닫을 가능성을 빼고 계산"
            />
            <Result
              label="위험반영 회수"
              value={q.data.riskAdjustedPaybackMonths}
              render={months}
              note="이 등급의 실측 생존율을 반영"
              emphasis
              missingNote="3년 안에 회수되지 않습니다"
            />
            <Result
              label="3년 기대손익"
              value={q.data.expectedProfit3y}
              render={signedMan}
              note="생존 확률로 가중한 값"
              emphasis
              tone={q.data.expectedProfit3y >= 0 ? "positive" : "negative"}
            />
          </div>

          {/* Caption lives in the component, not the screen — impossible to omit. */}
          {q.data.usedSeoulAverageRevenue ? (
            <p className={s.caption}>
              서울 상권 평균 매출 기준입니다 — 이 격자의 추정치가 아닙니다.
            </p>
          ) : null}
          {q.data.marginSensitive ? (
            <p className={s.sensitive}>
              결과가 마진 가정에 민감합니다 — 마진을 조금만 바꿔도 손익 부호가 뒤집힙니다.
            </p>
          ) : null}

          {q.data.gradeComparison?.length ? (
            <div className={s.compare}>
              <p className={s.compareTitle}>같은 조건, 자리만 다를 때</p>
              <table className={s.table}>
                <tbody>
                  {q.data.gradeComparison.map((row) => (
                    <tr key={row.grade} className={row.grade === grade ? s.rowOn : undefined}>
                      <th>{gradeLabel(row.grade)}</th>
                      <td>{signedMan(row.expectedProfit3y)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}
    </section>
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

/** null is a real answer here ("not recovered within 36 months"), not an error. */
function Result({
  label,
  value,
  render,
  note,
  missingNote,
  emphasis,
  tone,
}: {
  label: string;
  value: number | null;
  render: (v: number) => string;
  note: string;
  missingNote?: string;
  emphasis?: boolean;
  tone?: "positive" | "negative";
}) {
  const cls = [s.result, emphasis ? s.resultStrong : "", tone ? s[tone] : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls}>
      <span className={s.resultLabel}>{label}</span>
      <strong className={s.resultValue}>
        {value === null ? (missingNote ?? "정보 없음") : render(value)}
      </strong>
      <span className={s.resultNote}>{note}</span>
    </div>
  );
}
