import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { EstimateInput, EstimateResponse, RecoverySource, Sales } from "../api/types";
import { int, man, pct1, quarter } from "../lib/format";
import { ErrorState, Loading } from "./states";
import s from "./OccupancyCostCard.module.css";

// 월세만 비교하면 자리값의 일부만 보고 고르게 된다. 보증금은 이자만, 권리금은
// 못 건지는 몫만 잡아 셋을 «한 달에 나가는 돈» 하나로 합친다.
//
// 화면이 잊으면 안 되는 셋:
//   1. 산식은 POST /estimate 가 계산한다. 사본은 반드시 어긋난다.
//   2. burdenRate 가 null 이면 «정보 없음»이지 0 이 아니다(상권 밖 49.5%).
//   3. successionProb 는 «승계 확률»이다. 지불비율 원천이 없어 «회수»라고
//      부르지 않는다.

const DEBOUNCE_MS = 400;

export default function OccupancyCostCard({
  gridId,
  uptae,
  sales,
  rentMonthly,
  onRentChange,
}: {
  gridId: string;
  uptae: string;
  /** 부담률이 안 나올 때 «왜» 를 말하기 위해 받는다 — 상세가 이미 들고 있는
   *  값이라 estimate 응답을 늘리는 것보다 이쪽이 싸다. */
  sales: Sales;
  /** S4가 들고 있는 값 — 손익 카드와 같은 임대료를 쓴다(두 번 입력시키지 않는다) */
  rentMonthly: number | null;
  onRentChange: (v: number | null) => void;
}) {
  const [deposit, setDeposit] = useState<number | null>(null);
  const [goodwill, setGoodwill] = useState<number | null>(null);
  const [areaM2, setAreaM2] = useState<number | null>(null);
  const [floor, setFloor] = useState<number | null>(null);
  const [debounced, setDebounced] = useState<EstimateInput | null>(null);

  // 권리금 0과 지하층(-1)은 유효한 입력이라 «비었다»와 구분해야 한다.
  const ready =
    rentMonthly !== null && deposit !== null && goodwill !== null && areaM2 !== null && floor !== null;

  useEffect(() => {
    if (!ready) {
      setDebounced(null);
      return;
    }
    const input: EstimateInput = {
      gridId,
      uptae,
      deposit: deposit!,
      monthlyRent: rentMonthly!,
      askingGoodwill: goodwill!,
      areaM2: areaM2!,
      floor: floor!,
    };
    const t = setTimeout(() => setDebounced(input), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [ready, gridId, uptae, deposit, rentMonthly, goodwill, areaM2, floor]);

  const q = useQuery({
    queryKey: ["estimate", debounced],
    queryFn: () => api.estimate(debounced!),
    enabled: debounced !== null,
  });

  return (
    <section className={s.card}>
      <header className={s.head}>
        <h2 className={s.title}>한 달에 진짜로 나가는 돈</h2>
        <p className={s.lead}>
          보증금과 권리금도 결국 매달 빠져나가는 돈이라, 셋을 하나로 합쳐 봤어요.
        </p>
      </header>

      <div className={s.inputs}>
        <Field label="보증금" value={deposit} onChange={setDeposit} placeholder="예: 5,000" required />
        {/* 앱 전체가 «월 임대료»를 쓴다(S1·S2·S3·손익 카드). 같은 값을 공유하므로
            여기만 «월세»라 부르면 사용자가 다른 값으로 읽는다. */}
        <Field label="월 임대료" value={rentMonthly} onChange={onRentChange} placeholder="예: 250" required />
        <Field label="권리금" value={goodwill} onChange={setGoodwill} placeholder="없으면 0" required />
        <Field
          label="면적"
          value={areaM2}
          onChange={setAreaM2}
          unit="㎡"
          placeholder="예: 66"
          required
        />
        <Field
          label="층"
          value={floor}
          onChange={setFloor}
          unit="층"
          placeholder="지하는 -1"
          required
          allowNegative
        />
      </div>

      {!ready ? (
        <p className={s.prompt}>보증금·월 임대료·권리금과 면적·층을 넣으면 합쳐서 계산해 드려요.</p>
      ) : q.isPending ? (
        <Loading label="계산 중…" />
      ) : q.isError ? (
        <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} />
      ) : (
        <Result data={q.data} sales={sales} uptae={uptae} />
      )}
    </section>
  );
}

function Result({ data, sales, uptae }: {
  data: EstimateResponse;
  sales: Sales;
  uptae: string;
}) {
  const cost = data.costBreakdown;
  const total = data.effectiveCost;
  const band = data.effectiveCostBand;
  const hidden = total - cost.rent;
  // Segment widths share one scale so the bar reads as one month's money.
  const seg = (v: number) => (total > 0 ? `${(v / total) * 100}%` : "0%");

  return (
    <>
      <div className={s.headline}>
        <div className={s.headlineMain}>
          <span className={s.headlineLabel}>실질 월 점유비용</span>
          <strong className={s.headlineValue}>{man(total)}</strong>
          {/* 큰 숫자 하나만 내면 우리가 갖지 못한 확신을 표현하게 된다. 밴드는
              답을 흐리는 게 아니라 «이 자리가 얼마나 불확실한가»를 같이 말한다. */}
          <em className={s.headlineBand}>
            {man(band.low)} ~ {man(band.high)}
          </em>
        </div>
        {hidden > 0 ? (
          <p className={s.headlineGap}>
            월세만 보면 <b>{man(cost.rent)}</b>인데, 실제로는 매달{" "}
            <b className={s.gapAccent}>{man(hidden)}</b>이 더 나가요.
          </p>
        ) : null}
        {/* 대표값이 왜 밴드의 높은 쪽에 붙어 있는지 말하지 않으면, 사용자는
            그것을 «중간값»으로 읽는다. 보수적으로 잡았다는 사실 자체가 정보다. */}
        <p className={s.headlineBasis}>
          큰 숫자는 <b>권리금을 한 푼도 못 건진다</b>고 보고 계산했어요. 다음 사람이 이어받거나
          오래 쓰면 낮은 쪽에 가까워져요.
        </p>
      </div>

      {/* 한 달 치 돈 한 줄 — 월세 옆에 숨은 비용이 얼마나 붙는지가 보여야 한다. */}
      <div className={s.bar} role="img" aria-label={`월세 ${man(cost.rent)}, 숨은 비용 ${man(hidden)}`}>
        <i className={s.segRent} style={{ width: seg(cost.rent) }} />
        {cost.maintenance > 0 ? (
          <i className={s.segMaint} style={{ width: seg(cost.maintenance) }} />
        ) : null}
        <i className={s.segDeposit} style={{ width: seg(cost.depositOpportunity) }} />
        <i className={s.segGoodwill} style={{ width: seg(cost.premiumAmortized) }} />
      </div>

      <ul className={s.legend}>
        <Row tone="rent" name="월 임대료" value={cost.rent} note="그대로 나가요" />
        {cost.maintenance > 0 ? (
          <Row tone="maint" name="관리비" value={cost.maintenance} note="그대로 나가요" />
        ) : null}
        <Row
          tone="deposit"
          name="보증금 이자"
          value={cost.depositOpportunity}
          // 파라미터를 서버가 안 실어 보내면 각주를 생략한다. 0.04를 여기 박으면
          // 서버 기본값이 바뀌는 순간 화면만 거짓말을 하게 된다.
          note={
            data.paramsUsed
              ? `돌려받으니 이자만 · 연 ${pct1(data.paramsUsed.opportunityRate)}`
              : "돌려받으니 이자만"
          }
        />
        <Row
          tone="goodwill"
          name="권리금 손실분"
          value={cost.premiumAmortized}
          note={
            data.paramsUsed
              ? `전액 손실 기준 · ${int(data.paramsUsed.horizonMonths)}개월로 나눔`
              : "전액 손실 기준"
          }
        />
      </ul>

      {/* «회수»가 아니라 «승계» — 지불비율 원천이 없어 회수율이라 부를 수 없다.
          그리고 원천이 constant면 그것은 «이 자리의 값»이 아니라 모든 자리에
          같은 기본값이다. 측정값처럼 그리면 이 제품이 가장 경계하는 거짓이 된다. */}
      <SuccessionRow prob={data.successionProb} source={data.recoverySource} />

      <BurdenRow data={data} sales={sales} uptae={uptae} />

      <p className={s.notice}>{data.notice}</p>
    </>
  );
}

/**
 * 승계 확률과 **그 값이 어디서 왔는지**를 함께 낸다.
 *
 * `constant`는 아직 모델이 없어 모든 자리에 같은 기본값이 들어간 상태다. 숫자만
 * 크게 띄우면 사용자는 그것을 «이 자리의 측정치»로 읽는다 — 실제로는 옆 자리도,
 * 서울 어디도 같은 값이다. 그래서 constant일 때는 숫자를 죽이고 기본값임을
 * 먼저 말한다. 모델이 붙으면(`m2`) 그때 측정치로 승격된다.
 */
function SuccessionRow({ prob, source }: { prob: number; source: RecoverySource }) {
  const measured = source !== "constant";
  return (
    <div className={measured ? s.succession : s.successionFlat}>
      <span className={s.successionLabel}>나갈 때 다음 사람이 이어받을 가능성</span>
      <strong className={measured ? s.successionValue : s.successionValueDim}>{pct1(prob)}</strong>
      <p className={s.successionNote}>
        {source === "constant"
          ? "아직 이 자리를 계산한 값이 아니라 모든 자리에 같게 넣은 기본값이에요."
          : source === "survival_curve_proxy"
            ? "이 등급 자리들이 실제로 버틴 기록에서 나온 하한이에요. 이보다 나쁠 수는 있어도 좋기는 어려워요."
            : "이 자리의 승계 기록을 학습한 모델로 계산했어요."}
        {/* «보수적으로 잡았다»는 이 카드 맨 위 headlineBasis 가 이미 말한다
            («한 푼도 못 건진다고 보고 계산했어요»). 여기서는 이 값이 무엇이
            아닌지만 밝힌다. */}
        {" "}이어받는다는 뜻이지, 낸 권리금을 그만큼 돌려받는다는 뜻은 아니에요.
      </p>
      {/* 매물별 차등이 없다는 사실을 안 밝히면, 사용자는 이 값을 «내가 보고 있는
          그 가게»의 값으로 읽는다. 같은 골목 같은 업종이면 전부 같은 값이다. */}
      <p className={s.successionScope}>같은 자리·같은 업종이면 모두 같은 값이에요.</p>
    </div>
  );
}

/** 매출이 없는 이유를 관측으로 돌려준다.
 *
 *  상권분석 매출은 카드 기반 추정이라 점포가 한두 곳이면 개별 사업자 매출이
 *  드러나 공표하지 않는다(1곳 공표율 9.7% · 2곳 26.2% · 20곳 이상 99.2%).
 *  «없음»은 계산 실패가 아니라 «이 상권엔 그 업종이 거의 없다»는 사실이고,
 *  그것 자체가 입지 정보다.
 *
 *  서울 평균으로 메우지 않는다. 결측이 점포 적은 상권에 몰려 있어서, 평균을
 *  붙이면 한산한 골목에 번화가 값이 붙는다. */
function WhyNoRevenue({ sales, uptae }: { sales: Sales; uptae: string }) {
  if (!sales.available) {
    return <p>이 자리는 상권 밖이라 매출 통계가 없어요.</p>;
  }
  if (sales.uptaeStores === null) {
    return (
      <p>
        {uptae}은(는) 상권 매출 통계의 업종 분류에 없어서 «매출 대비 얼마인지»를
        낼 수 없어요.
      </p>
    );
  }
  if (sales.uptaeStores === 0) {
    return (
      <p>
        이 상권엔 {uptae} 가게가 <b>한 곳도 없어서</b> 매출 통계가 없어요.
        경쟁이 없다는 뜻일 수도, 이 자리에 맞지 않는 업종이라는 뜻일 수도 있어요.
      </p>
    );
  }
  return (
    <p>
      이 상권엔 {uptae} 가게가 <b>{int(sales.uptaeStores)}곳</b>뿐이라 매출
      통계가 공표되지 않았어요. 가게가 적으면 개별 매출이 드러나서 서울시가
      비공개합니다.
    </p>
  );
}

function BurdenRow({ data, sales, uptae }: {
  data: EstimateResponse;
  sales: Sales;
  uptae: string;
}) {
  if (data.burdenRate === null) {
    return (
      <div className={s.burdenNone}>
        <strong>부담률은 계산하지 못했어요</strong>
        {/* 갈래마다 사정이 다르고, «그래도 위 점유비용은 유효하다» 는 어느
            갈래에서나 같다 — 갈래 안에 두면 같은 문장이 세 번 나온다. */}
        <WhyNoRevenue sales={sales} uptae={uptae} />
        <p>위 실질 점유비용은 그대로 보셔도 됩니다.</p>
      </div>
    );
  }

  return (
    <div className={s.burden}>
      <div className={s.burdenMain}>
        <span className={s.burdenLabel}>매출에서 자리값이 차지하는 몫</span>
        <strong className={s.burdenValue}>{pct1(data.burdenRate)}</strong>
        {data.burdenRateBand ? (
          <em className={s.burdenBand}>
            {pct1(data.burdenRateBand.low)} ~ {pct1(data.burdenRateBand.high)}
          </em>
        ) : null}
      </div>
      <p className={s.burdenNote}>
        {data.monthlyRevenue !== null ? `월 매출 ${man(data.monthlyRevenue)} 기준` : ""}
        {data.revenueAsOfQuarter ? ` · ${quarter(data.revenueAsOfQuarter)}` : ""}
      </p>
      {/* 여기는 자리 하나를 보는 화면이라 «순위» 이야기를 꺼낼 자리가 아니다.
          해상도 한계만 말한다 — 순위 비교 경고는 후보를 여럿 놓는 S5의 몫. */}
      <p className={s.burdenTied}>
        이 매출은 상권 단위 값이라 바로 옆 자리와 같은 값이에요. 이 자리만의 매출을 예측한 값이
        아니에요.
      </p>
    </div>
  );
}

function Row({
  tone,
  name,
  value,
  note,
}: {
  tone: "rent" | "maint" | "deposit" | "goodwill";
  name: string;
  value: number;
  note: string;
}) {
  return (
    <li className={s.legendRow}>
      <i className={s[`dot_${tone}`]} />
      <span className={s.legendName}>{name}</span>
      <strong className={s.legendValue}>{man(value)}</strong>
      <span className={s.legendNote}>{note}</span>
    </li>
  );
}

function Field({
  label,
  value,
  onChange,
  unit = "만원",
  placeholder,
  required,
  allowNegative,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  unit?: string;
  placeholder?: string;
  required?: boolean;
  allowNegative?: boolean;
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
          min={allowNegative ? undefined : 0}
          value={value ?? ""}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        />
        <span className={s.unit}>{unit}</span>
      </span>
    </label>
  );
}
