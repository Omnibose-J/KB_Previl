import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { GoodwillAssetInput, GoodwillInput, GridDetail } from "../api/types";
import { int, man, pct1, signedMan, yearsLabel } from "../lib/format";
import { ErrorState, Loading } from "./states";
import s from "./GoodwillCard.module.css";

// 권리금 협상 리포트. 입력은 사용자가 아는 것만(호가·잔여기간·유형자산) 받고,
// 근거 값(M, M̄, r, d, 조정계수)은 전부 서버가 갖고 출처와 함께 내려온다.
// 상권 밖 격자는 입력칸 자체를 안 준다 — 매출 근거가 없으면 무형가치가 성립하지
// 않고, 그걸 지어내는 것이 권리금판 목업이다.

const DEBOUNCE_MS = 500;

const REFERENCE_LABEL = {
  below_band: { text: "참고 범위보다 낮게 부르고 있어요", cls: "refGreen" },
  within_band: { text: "참고 범위 안이에요", cls: "refGray" },
  above_band: { text: "참고 범위보다 높아요, 깎아볼 만해요", cls: "refOrange" },
} as const;

/** 생존곡선이 36개월치라 서버는 어떤 잔여 계약이 와도 3년 안에서 멈춘다.
 *  숫자로 10년을 받아놓고 조용히 깎느니, 컨트롤이 상한을 먼저 말하게 한다. */
const LEASE_MIN = 0.5;
const LEASE_MAX = 3;
const LEASE_STEP = 0.5;

export default function GoodwillCard({ d, uptae }: { d: GridDetail; uptae: string }) {
  const [asking, setAsking] = useState<number | null>(null);
  const [leaseYears, setLeaseYears] = useState(LEASE_MAX);
  const [assets, setAssets] = useState<GoodwillAssetInput[]>([]);
  const [debounced, setDebounced] = useState<GoodwillInput | null>(null);

  const ready = asking !== null;

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
      leaseRemainingYears: leaseYears,
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

  // sales.available 은 «상권 안이냐» 만 본다. 상권 «안» 이어도 그 업종의 매출이
  // 공표되지 않은 조합이 33.6% 인데, 그걸 안 거르면 /goodwill 이 503 을 내고
  // 화면에 «데이터를 불러오지 못했어요 + 다시 시도» 가 떴다 — 다시 눌러도 없는
  // 통계는 생기지 않는다. 권리금은 산출 전체가 매출 파생이라 여기서 멈춘다.
  if (!d.sales.available || !d.sales.uptaePublished) {
    return (
      <section className={s.card}>
        <Head />
        <p className={s.unavailable}>
          {!d.sales.available
            ? "이 자리는 상권 밖이라 매출 기록이 없어서 권리금 참고가를 계산할 수 없어요."
            : d.sales.uptaeStores === null
              ? `${uptae}은(는) 상권 매출 통계의 업종 분류에 없어서 권리금 참고가를 계산할 수 없어요.`
              : d.sales.uptaeStores === 0
                ? `이 상권엔 ${uptae} 가게가 한 곳도 없어서 매출 통계가 없어요. ` +
                  "권리금 참고가는 같은 업종 매출을 기준으로 잡기 때문에 계산할 수 없어요."
                : `이 상권엔 ${uptae} 가게가 ${int(d.sales.uptaeStores)}곳뿐이라 매출 통계가 ` +
                  "공표되지 않았어요. 가게가 적으면 개별 매출이 드러나서 서울시가 비공개합니다."}
        </p>
      </section>
    );
  }

  return (
    <section className={s.card}>
      <Head />

      {/* 입력 행 */}
      <div className={s.inputs}>
        <NumField label="부르는 권리금" required value={asking} onChange={setAsking} unit="만원" placeholder="예: 3,000" />
        <LeaseSlider value={leaseYears} onChange={setLeaseYears} />
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
        <p className={s.prompt}>부르는 권리금을 넣으면 계산해 드려요.</p>
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

function LeaseSlider({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className={s.leaseField}>
      <div className={s.leaseHead}>
        <span className={s.fieldLabel}>계약 남은 기간</span>
        <strong>{yearsLabel(value)}</strong>
      </div>
      <input
        className={s.leaseRange}
        type="range"
        min={LEASE_MIN}
        max={LEASE_MAX}
        step={LEASE_STEP}
        value={value}
        aria-label="계약 남은 기간"
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <div className={s.leaseTicks}>
        <span>{yearsLabel(LEASE_MIN)}</span>
        <span>{yearsLabel(LEASE_MAX)}</span>
      </div>
      <p className={s.leaseCap}>기록이 3년치라 3년까지만 셀 수 있어요.</p>
    </div>
  );
}

function Head() {
  return (
    <div className={s.head}>
      {/* 부제는 진입 카드에만 둔다 — 한 번 누르면 열리는 창이라, 같은 두 줄을
          한 클릭 만에 다시 읽게 된다. 아래 notice 가 이 창의 한계를 따로 밝힌다. */}
      <h2>부르는 권리금, 적당한가요?</h2>
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

      {/* 호가 3분해 — 위 «괴리»가 얼마나 비싼지라면, 이건 그 돈이 무엇의 값인지다.
          점수만 보여주면 사용자는 아무것도 못 한다. 항목별로 쪼개야 어느 항목의
          근거를 물어볼지가 정해진다 (기획서 §4.3.1). */}
      <Decomposition d={r.decomposition} asking={r.askingGoodwill} />

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
          <dt>이 상권 점포당 월매출</dt>
          <dd>
            {man(r.monthlyRevenue)} <em>같은 상권 안 자리는 같은 값이에요</em>
          </dd>
        </div>
        <div>
          {/* «서울 중간 월매출»이라고 하면 «서울 점포의 중간 매출»로 읽힌다.
              실제로는 상권 1,400여 곳의 점포당 매출을 줄 세운 가운데 값이라,
              점포 수로 가중한 값과 37~60% 벌어진다. 단위를 이름에 박는다. */}
          <dt>서울 상권 중간값</dt>
          <dd>
            {man(r.benchmarkMonthlyRevenue)}{" "}
            <em>
              같은 업종 상권들의 점포당 매출 중 가운데 값
              {r.benchmarkWarning ? ` · ${r.benchmarkWarning}` : ""}
            </em>
          </dd>
        </div>
        <div>
          <dt>영업이익률</dt>
          <dd>
            {pct1(r.operatingMargin)} <em>{r.operatingMarginSource}</em>
          </dd>
        </div>
        <div>
          <dt>할인율</dt>
          <dd>
            {pct1(r.discountRate)} <em>{r.discountRateSource}</em>
          </dd>
        </div>
        <div>
          <dt>계산 기간</dt>
          <dd>
            {yearsLabel(r.valuationYears)}{" "}
            {/* «둘 중 짧은 쪽»만 말하면 어느 쪽이 물렸는지가 안 보인다. 계약이
                짧아서 짧은 것과, 기록이 3년치뿐이라 더 못 세는 것은 사용자가
                할 수 있는 일이 다르다(전자는 협상, 후자는 판단 보정). */}
            <em>
              {r.leaseRemainingYears < r.expectedSurvivalYears
                ? `남은 계약 ${yearsLabel(r.leaseRemainingYears)}이 더 짧아서 그만큼만 셌어요`
                : `이런 자리가 버티는 기간이 ${yearsLabel(r.expectedSurvivalYears)}이라 거기서 멈췄어요`}
            </em>
          </dd>
        </div>
      </dl>

      {/* 상한이 «3년치 기록»이라는 데이터 사정에서 온다는 것과, 그래서 값이
          어느 방향으로 치우치는지를 밝힌다. 이걸 숨기면 잔여 계약이 긴 매물의
          참고가가 왜 안 오르는지 사용자가 알 방법이 없다. */}
      {r.leaseRemainingYears >= r.expectedSurvivalYears ? (
        <p className={s.capNote}>
          버티는 기간은 <b>3년치 기록</b>으로만 계산해서 3년을 넘지 않아요. 계약이 더 길다면{" "}
          <b>실제 가치는 이보다 높다</b>고 보셔야 해요.
        </p>
      ) : null}

      <SensitivityPivot r={r} />

      <p className={s.notice}>{r.notice}</p>
    </>
  );
}

/**
 * 호가 = 시설 + 영업 + 바닥. 앞의 둘은 산정 관행이 있고, 바닥은 «부르는 것이
 * 값»이라 분쟁의 핵심이다 — 그래서 바닥만 벤치마크 대비로 따로 세운다.
 *
 * `floorKey`는 잔차라 음수가 나올 수 있다(호가 < 시설+영업). 그건 계산 실패가
 * 아니라 «근거보다 싸게 부른다»는 사실이므로 음수 그대로 말한다. 다만 쌓기
 * 막대로는 그릴 수 없어 그 경우 막대를 생략한다 — 없는 길이를 지어내지 않는다.
 */
function Decomposition({
  d,
  asking,
}: {
  d: import("../api/types").GoodwillDecomposition;
  asking: number;
}) {
  const parts = [
    { key: "facility", name: "시설", value: d.facility, note: "인테리어·집기 · 내용연수 정액 감가" },
    { key: "business", name: "영업", value: d.business, note: "단골·매출로 버는 몫" },
    { key: "floorKey", name: "바닥", value: d.floorKey, note: "자리 그 자체의 값" },
  ] as const;
  const stackable = d.facility >= 0 && d.business >= 0 && d.floorKey >= 0 && asking > 0;

  return (
    <section className={s.decomp}>
      <div className={s.decompHead}>
        <h4>부르는 값이 무엇의 값인지</h4>
        <p>호가 {man(asking)}을 항목별로 쪼갰어요.</p>
      </div>

      {stackable ? (
        <div className={s.decompBar} role="img" aria-label={`시설 ${man(d.facility)}, 영업 ${man(d.business)}, 바닥 ${man(d.floorKey)}`}>
          {parts.map((p) => (
            <i
              key={p.key}
              className={s[`decompSeg_${p.key}`]}
              style={{ width: `${(p.value / asking) * 100}%` }}
            />
          ))}
        </div>
      ) : null}

      <ul className={s.decompList}>
        {parts.map((p) => (
          <li key={p.key} className={s.decompRow}>
            <i className={s[`decompDot_${p.key}`]} />
            <span className={s.decompName}>{p.name}</span>
            <strong className={s.decompValue}>{man(p.value)}</strong>
            <span className={s.decompNote}>{p.note}</span>
          </li>
        ))}
      </ul>

      {d.floorKey < 0 ? (
        <p className={s.decompUnder}>
          바닥권리금이 마이너스예요. 시설과 영업의 값만 따져도 호가보다 크다는 뜻이라, 자리값을
          따로 붙이지 않고 부르고 있어요.
        </p>
      ) : null}

      {/* 유형자산을 안 넣으면 시설이 0이 되고, 그러면 바닥 = 호가 − 영업이라
          위 «괴리»와 같은 숫자가 된다. 같은 값이 두 이름으로 보이면 사용자는
          둘을 다른 것으로 읽는다 — 왜 그런지 말해주고 입력을 유도한다. */}
      {d.facility === 0 ? (
        <p className={s.decompUnder}>
          인테리어·집기를 아직 안 넣으셔서 시설 몫이 0이에요. 그래서 바닥권리금이 위 «괴리»와 같은
          값으로 잡혀요. 위에서 <b>유형자산 추가</b>로 넣으면 그만큼 바닥에서 빠져요.
        </p>
      ) : null}

      {/* 기획서 §4.3.1은 «동일 상권 평균 대비 62% 높습니다»까지 요구하지만, 그
          평균을 만들려면 상권별 바닥권리금 표본이 있어야 한다 — 권리금은 신고
          의무가 없어 그 표본이 세상에 없다. 없는 비교를 지어내지 않고, 무엇이
          없는지 말한다. */}
      <p className={s.decompBench}>
        바닥권리금은 «부르는 것이 값»이라 비교할 시세가 없어요. 그래서 «평균 대비 얼마»는 내지
        않았어요 — 대신 위 참고가와 얼마나 벌어지는지로 보세요.
      </p>
    </section>
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
              {yearsLabel(v)}
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
      <p className={s.sensCap}>산정 기간 {yearsLabel(y)} 기준 · 굵은 칸이 이 리포트의 가정</p>
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
