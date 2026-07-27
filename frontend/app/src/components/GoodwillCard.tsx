import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { GoodwillAssetInput, GoodwillInput, GridDetail } from "../api/types";
import { int, man, pct1, signedMan } from "../lib/format";
import { ErrorState, Loading } from "./states";
import s from "./GoodwillCard.module.css";

// 권리금 협상 리포트 — goodwill-report-design §8-C (증권사 리서치 포맷).
// Inputs are ONLY what the user knows (호가·잔여기간·유형자산); every basis
// number (M, M̄, r, d, 조정계수) is server-owned and rendered from the
// response with its source — the client never computes valuation parts.
// Out-of-trade-area grids get no inputs at all: with no revenue basis the
// intangible value cannot exist, and faking it is the goodwill version of a
// mockup (§3).

const DEBOUNCE_MS = 500;

const REFERENCE_LABEL = {
  below_band: { text: "호가가 참고 밴드 아래", cls: "refGreen" },
  within_band: { text: "호가가 참고 밴드 안", cls: "refGray" },
  above_band: { text: "호가가 참고 밴드 위 — 협상 여지", cls: "refOrange" },
} as const;

export default function GoodwillCard({ d, uptae }: { d: GridDetail; uptae: string }) {
  const [asking, setAsking] = useState<number | null>(null);
  const [leaseYears, setLeaseYears] = useState<number | null>(null);
  const [assets, setAssets] = useState<GoodwillAssetInput[]>([]);
  const [debounced, setDebounced] = useState<GoodwillInput | null>(null);

  const ready = asking !== null && leaseYears !== null;

  useEffect(() => {
    if (!ready) {
      setDebounced(null);
      return;
    }
    // A half-typed asset row must never reach the valuation: an empty name /
    // zero cost / zero life is not data, and the server 422s on gt=0 fields.
    const complete = assets.filter(
      (a) => a.name.trim() !== "" && a.acquisitionCost > 0 && a.usefulLifeYears > 0,
    );
    const input: GoodwillInput = {
      gridId: d.gridId,
      uptae,
      askingGoodwill: asking!,
      leaseRemainingYears: leaseYears!,
      ...(complete.length > 0 ? { assets: complete } : {}),
    };
    const t = setTimeout(() => setDebounced(input), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [ready, d.gridId, uptae, asking, leaseYears, assets]);

  const q = useQuery({
    queryKey: ["goodwill", debounced],
    queryFn: () => api.goodwill(debounced!),
    enabled: debounced !== null,
    placeholderData: (prev) => prev, // keep last real report during retyping
    retry: 0,
  });

  if (!d.sales.available) {
    return (
      <section className={s.card}>
        <Head />
        <p className={s.unavailable}>
          매출 근거 없음 — 이 격자는 상권 밖이라 무형재산을 계산할 매출 데이터가 없어 권리금
          리포트를 제공할 수 없습니다.
        </p>
      </section>
    );
  }

  return (
    <section className={s.card}>
      <Head />

      {/* 입력 행 */}
      <div className={s.inputs}>
        <NumField label="권리금 호가" required value={asking} onChange={setAsking} unit="만원" placeholder="예: 3,000" />
        <NumField label="임대차 잔여" required value={leaseYears} onChange={setLeaseYears} unit="년" placeholder="예: 3" />
        <button
          className={s.addAsset}
          onClick={() =>
            // Zeroed row on purpose: incomplete rows are excluded from the
            // payload, so nothing invented ever reaches the server.
            setAssets((a) => [...a, { name: "", acquisitionCost: 0, ageYears: 0, usefulLifeYears: 0 }])
          }
        >
          + 유형자산 추가
        </button>
      </div>

      {assets.length > 0 ? (
        <div className={s.assets}>
          {assets.map((a, i) => (
            <div key={i} className={s.assetRow}>
              <input
                className={s.assetName}
                placeholder="예: 주방 설비"
                value={a.name}
                onChange={(e) => patchAsset(setAssets, i, { name: e.target.value })}
              />
              <AssetNum value={a.acquisitionCost} unit="만원 취득" onChange={(v) => patchAsset(setAssets, i, { acquisitionCost: v })} />
              <AssetNum value={a.ageYears} unit="년 경과" onChange={(v) => patchAsset(setAssets, i, { ageYears: v })} />
              <AssetNum value={a.usefulLifeYears} unit="년 내용연수" onChange={(v) => patchAsset(setAssets, i, { usefulLifeYears: v })} />
              <button className={s.assetDel} onClick={() => setAssets((arr) => arr.filter((_, j) => j !== i))}>
                삭제
              </button>
            </div>
          ))}
        </div>
      ) : null}

      {!ready ? (
        <p className={s.prompt}>호가와 임대차 잔여기간을 넣으면 계산합니다.</p>
      ) : q.isPending ? (
        <Loading label="추정 참고가 계산 중…" />
      ) : q.isError ? (
        <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} />
      ) : (
        <Result r={q.data} />
      )}
    </section>
  );
}

function Head() {
  return (
    <div className={s.head}>
      <h2>권리금 협상 리포트</h2>
      <p>호가가 실측 기반 추정 참고가의 어디쯤인지 봅니다. 감정평가가 아닌 참고 정보입니다.</p>
    </div>
  );
}

function Result({ r }: { r: import("../api/types").GoodwillResponse }) {
  const ref = REFERENCE_LABEL[r.negotiationReference];
  return (
    <>
      {/* 헤드라인 */}
      <div className={s.headline}>
        <span className={s[ref.cls]}>{ref.text}</span>
        <p className={s.estimate}>
          추정 참고가 <strong>{man(r.estimatedGoodwill)}</strong>
          <em>
            참고 밴드 {man(r.bandLow)} ~ {man(r.bandHigh)}
          </em>
        </p>
      </div>

      {/* 괴리 행 */}
      <div className={s.gapRow}>
        <div>
          <span>호가</span>
          <strong>{man(r.askingGoodwill)}</strong>
        </div>
        <div>
          <span>추정 참고가</span>
          <strong>{man(r.estimatedGoodwill)}</strong>
        </div>
        <div>
          <span>괴리</span>
          <strong>
            {signedMan(r.askingGap)}
            {r.askingGapRate !== null ? ` (${pct1(r.askingGapRate)})` : ""}
          </strong>
        </div>
      </div>

      {/* Valuation 분해 */}
      <p className={s.valuation}>
        무형 {man(r.intangibleValue)} + 유형 {man(r.tangibleValue)}
        <em>
          조정계수 {r.adjustmentFactor}
          {r.adjustmentReasons.length > 0 ? ` — ${r.adjustmentReasons.join(" · ")}` : ""}
        </em>
      </p>

      {r.tangibleAssets.length > 0 ? (
        <table className={s.assetTable}>
          <thead>
            <tr>
              <th>유형자산</th>
              <th>취득가</th>
              <th>잔존율</th>
              <th>평가액</th>
            </tr>
          </thead>
          <tbody>
            {r.tangibleAssets.map((a, i) => (
              <tr key={i}>
                <td>{a.name || "이름 없음"}</td>
                <td>{man(a.acquisitionCost)}</td>
                <td>{pct1(a.residualRate)}</td>
                <td>{man(a.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {/* 근거 행렬 — 전부 응답 필드, 출처 병기 */}
      <dl className={s.basis}>
        <div>
          <dt>상권 매출 M</dt>
          <dd>
            월 {man(r.monthlyRevenue)} <em>상권 단위 — 같은 상권 안 자리는 동일</em>
          </dd>
        </div>
        <div>
          <dt>벤치마크 M̄</dt>
          <dd>
            월 {man(r.benchmarkMonthlyRevenue)}{" "}
            <em>
              서울 전체 × 동일 업종 (Level {r.benchmarkLevel})
              {r.benchmarkWarning ? ` · ${r.benchmarkWarning}` : ""}
            </em>
          </dd>
        </div>
        <div>
          <dt>영업이익률 r</dt>
          <dd>
            {pct1(r.operatingMargin)} <em>{r.operatingMarginSource} · 임대료 차감 후</em>
          </dd>
        </div>
        <div>
          <dt>할인율 d</dt>
          <dd>
            {pct1(r.discountRate)} <em>{r.discountRateSource}</em>
          </dd>
        </div>
        <div>
          <dt>산정 기간 N</dt>
          <dd>
            {int(r.valuationYears)}년{" "}
            <em>
              min(기대 존속 {r.expectedSurvivalYears.toFixed(1)}년, 임대차 잔여 {int(r.leaseRemainingYears)}년)
            </em>
          </dd>
        </div>
      </dl>

      <SensitivityPivot r={r} />

      <p className={s.notice}>{r.notice}</p>
    </>
  );
}

/** 27 combinations pivoted to a 3×3 matrix (margin × discount) with a year
 *  toggle — every value stays reachable, nothing is dropped, but the table
 *  reads in one glance instead of 27 rows. The served combination is marked. */
function SensitivityPivot({ r }: { r: import("../api/types").GoodwillResponse }) {
  const margins = [...new Set(r.sensitivity.map((x) => x.operatingMargin))].sort((a, b) => a - b);
  const rates = [...new Set(r.sensitivity.map((x) => x.discountRate))].sort((a, b) => a - b);
  const years = [...new Set(r.sensitivity.map((x) => x.years))].sort((a, b) => a - b);
  const [yr, setYr] = useState<number | null>(null);
  const y = yr !== null && years.includes(yr) ? yr : years.includes(r.valuationYears) ? r.valuationYears : years[Math.floor(years.length / 2)];

  if (r.sensitivity.length === 0) return null;

  const cell = (m: number, dr: number) =>
    r.sensitivity.find((x) => x.operatingMargin === m && x.discountRate === dr && x.years === y) ?? null;

  return (
    <div className={s.sens}>
      <div className={s.sensHead}>
        <p className={s.sensTitle}>가정을 바꾸면</p>
        <div className={s.yearChips}>
          {years.map((v) => (
            <button key={v} className={v === y ? s.yearOn : s.year} onClick={() => setYr(v)}>
              {int(v)}년
            </button>
          ))}
        </div>
      </div>
      <table className={s.sensTable}>
        <thead>
          <tr>
            <th>영업이익률 ↓ / 할인율 →</th>
            {rates.map((dr) => (
              <th key={dr}>{pct1(dr)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {margins.map((m) => (
            <tr key={m}>
              <td>{pct1(m)}</td>
              {rates.map((dr) => {
                const c = cell(m, dr);
                const served =
                  m === r.operatingMargin && dr === r.discountRate && y === r.valuationYears;
                return (
                  <td key={dr} className={served ? s.sensOn : undefined}>
                    {c ? man(c.estimatedGoodwill) : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className={s.sensCap}>산정 기간 {int(y)}년 기준 · 굵은 칸이 이 리포트의 가정</p>
    </div>
  );
}

function patchAsset(
  set: React.Dispatch<React.SetStateAction<GoodwillAssetInput[]>>,
  i: number,
  patch: Partial<GoodwillAssetInput>,
) {
  set((arr) => arr.map((a, j) => (j === i ? { ...a, ...patch } : a)));
}

function NumField({
  label,
  value,
  onChange,
  unit,
  placeholder,
  required,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  unit: string;
  placeholder: string;
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

function AssetNum({ value, unit, onChange }: { value: number; unit: string; onChange: (v: number) => void }) {
  return (
    <span className={s.assetNum}>
      <input
        type="number"
        min={0}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={unit}
      />
      <em>{unit}</em>
    </span>
  );
}
