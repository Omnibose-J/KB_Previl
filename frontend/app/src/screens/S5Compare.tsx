import { useCallback, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { api } from "../api/client";
import type { CompareItem, CompareResponse, GridCell, Point } from "../api/types";
import AreaPicker from "../components/AreaPicker";
import GridMap from "../components/GridMap";
import { ErrorState, Loading } from "../components/states";
import { man, pct0, pct1 } from "../lib/format";
import s from "./S5Compare.module.css";

// S5 비교 — 기획서 §1.4의 사용자를 위한 입구다. 이 사람은 «어디가 좋아?»를
// 묻지 않는다. 부동산 두세 곳을 돌고 후보 1~3개를 이미 손에 쥔 채 «여기
// 계약해도 되나요»를 묻는다. 그래서 이 화면은 탐색이 아니라 판정이다.
//
// 화면이 증명해야 하는 것은 단 하나 — 정렬 기준을 바꾸면 순위가 실제로 뒤집힌다
// (기획서 §3.3). 표만 두 개 놓으면 «숫자가 다르네»로 읽히고 끝이라, 두 순위를
// 선으로 이어 **교차가 눈에 보이게** 그린다. 심사위원은 산식이 아니라 화면을 본다.
//
// 위치는 지도 클릭으로만 잡는다. 번지를 쳐서 찾는 것은 지오코딩 키가 없어 못
// 하고, 없는 것을 있는 척하느니 «지도에서 찍기»가 정직하다. 대신 아는 동네로
// 날아가는 것까지는 우리 데이터로 되므로(행정동 목록 = /api/areas), 지도 머리에
// S3 와 같은 지역 찾기를 둔다 — 찍은 칸의 대략 주소는 말풍선이 답한다.

const MAX_CANDIDATES = 3;
// 이 화면이 증명하는 것은 «정렬 기준을 바꾸면 순위가 뒤집힌다»이고, 한 곳으로는
// 그 문장이 성립하지 않는다. 예전에는 1건도 통과시켜 «이 후보들은 순서가 같아요»
// 라는 비교 결과가 후보 하나짜리로 나왔다.
const MIN_CANDIDATES = 2;
const SLOT_LABELS = ["A", "B", "C"] as const;

// 권리금을 몇 달에 나눠 담을지. 결과를 가장 크게 흔드는 값인데 예전에는 36개월로
// 고정돼 있었다 — 같은 후보가 2년이면 516만, 8년이면 329만으로 순위까지 바뀐다.
// 서버는 1~120개월을 받으므로(app.py CostParamsInput) 그 범위를 연 단위로 연다.
const LEASE_MIN = 1;
const LEASE_MAX = 10;

interface Slot {
  label: string;
  cell: GridCell | null;
  deposit: number | null;
  rentMonthly: number | null;
  goodwill: number | null;
  areaM2: number | null;
  floor: number | null;
}

const emptySlot = (i: number): Slot => ({
  label: SLOT_LABELS[i],
  cell: null,
  deposit: null,
  rentMonthly: null,
  goodwill: null,
  areaM2: null,
  floor: null,
});

/** 서버에 보낼 수 있는 후보인가 — 위치와 다섯 값이 모두 있어야 한다(전부 필수).
 *  권리금 0(무권리)과 층 -1(지하)은 유효한 입력이므로 null과 구분한다. */
function isComplete(slot: Slot): boolean {
  return (
    slot.cell !== null &&
    slot.deposit !== null &&
    slot.rentMonthly !== null &&
    slot.goodwill !== null &&
    slot.areaM2 !== null &&
    slot.floor !== null
  );
}

export default function S5Compare({ go }: { go: (s: Screen) => void }) {
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const [uptae, setUptae] = useState<string | null>(null);
  const [slots, setSlots] = useState<Slot[]>([emptySlot(0), emptySlot(1)]);
  const [active, setActive] = useState(0);

  const compare = useMutation({
    mutationFn: api.compare,
  });

  const [leaseYears, setLeaseYears] = useState<number>(3);

  const ready = slots.filter(isComplete);
  // 값은 넣었는데 자리를 안 찍은 후보. 조용히 빼면 사용자는 두 곳을 비교한 줄
  // 알고 결과를 읽는다 — 무엇이 왜 빠졌는지 이름으로 말한다.
  const droppedForCell = slots.filter(
    (sl) => sl.cell === null && (sl.deposit !== null || sl.rentMonthly !== null),
  );
  const canCompare = uptae !== null && ready.length >= MIN_CANDIDATES;

  const patch = (i: number, next: Partial<Slot>) =>
    setSlots((prev) => prev.map((sl, j) => (j === i ? { ...sl, ...next } : sl)));

  // 지도 클릭은 «지금 편집 중인 후보»의 위치가 된다.
  //
  // GridMap은 지도를 mount 때 한 번만 만들고(GridMap.tsx의 `[]` deps) 클릭
  // 핸들러가 **최초 렌더의 onSelect를 가둔다**. 그래서 active를 클로저로 읽으면
  // 영원히 0(=A)이 잡혀 모든 클릭이 A만 덮어쓴다. ref로 호출 시점에 읽는다.
  const activeRef = useRef(active);
  activeRef.current = active;
  const onPick = useCallback((cell: GridCell) => {
    setSlots((prev) => prev.map((sl, j) => (j === activeRef.current ? { ...sl, cell } : sl)));
  }, []);

  // 지도는 «격자가 실제로 그려지는 곳»에서 열려야 한다. 서울 전역 줌에서는
  // /grids가 413(상한 2000)이라 한 칸도 안 나오고, 빈 지도는 «여긴 데이터가
  // 없다»로 읽힌다 — 찍을 게 없으니 이 화면 자체가 멈춘다.
  // 시드는 임의 좌표가 아니라 그 업종의 실제 추천 1위다.
  const seed = useQuery({
    queryKey: ["recommend", uptae, "compare-seed"],
    queryFn: () => api.recommend(uptae!, [], 24),
    enabled: uptae !== null,
    staleTime: Infinity,
  });

  // 지역 찾기로 옮긴 자리. 한 번 옮기면 그 뒤 자리를 찍어도 지도는 그대로 둔다 —
  // 찍은 칸은 이미 화면 안에 있어서, 거기로 다시 날아가면 시야만 흔들린다.
  const [jump, setJump] = useState<Point | null>(null);

  const focus = useMemo(() => {
    if (jump) return jump;
    const picked = slots.find((sl) => sl.cell)?.cell?.center;
    if (picked) return picked;
    const items = seed.data?.items ?? [];
    // 1위를 그냥 쓰면 안 된다 — 실측으로 한식 1위가 관악산 자락이라 반경 안에
    // 채점된 칸이 하나뿐이었다. 지도가 «찍을 게 없는» 상태로 열린다.
    // 상권 안(salesAvailable) 후보는 상업지라 이웃 칸이 있다는 것이 보장에 가깝다.
    return (items.find((it) => it.salesAvailable) ?? items[0])?.center ?? null;
  }, [jump, slots, seed.data]);

  const run = () => {
    if (!uptae) return;
    // label을 실어 보내면 서버가 그대로 되싣는다. 순서에 기대지 않는 이유는
    // 같은 격자에 후보가 둘일 수 있어서다(같은 건물 1층/2층) — gridId로는
    // 후보를 구분할 수 없다.
    compare.mutate({
      uptae,
      costParams: { horizonMonths: leaseYears * 12 },
      candidates: ready.map((sl) => ({
        label: sl.label,
        gridId: sl.cell!.gridId,
        deposit: sl.deposit!,
        monthlyRent: sl.rentMonthly!,
        askingGoodwill: sl.goodwill!,
        areaM2: sl.areaM2!,
        floor: sl.floor!,
      })),
    });
  };

  return (
    <div className={s.page}>
      <div className={s.crumb}>
        <button className={s.back} onClick={() => go({ name: "landing" })}>
          ← 처음으로
        </button>
        <span className={s.crumbPath}>손에 쥔 매물 비교</span>
        <span />
      </div>

      <header className={s.hero}>
        <h1 className={s.h1}>
          월세가 싼 자리가
          <br />
          <em>정말 싼 자리일까요</em>
        </h1>
        <p className={s.heroSub}>
          보증금과 권리금까지 한 달치로 바꿔서 다시 줄을 세워 드려요. 후보를 최대 세 곳까지 넣을 수
          있어요.
        </p>
      </header>

      <main className={s.body}>
        <section className={s.setup}>
          {/* ── 업종 ─────────────────────────────────────────────── */}
          <div className={s.block}>
            <h2 className={s.blockH}>
              <i>1</i> 업종을 고르세요
            </h2>
            {meta.isPending ? (
              <Loading label="업종 목록을 불러오는 중…" />
            ) : meta.isError ? (
              <ErrorState onRetry={() => meta.refetch()} detail={String(meta.error)} />
            ) : (
              <div className={s.chips}>
                {meta.data.uptae.map((u) => (
                  <button
                    key={u}
                    className={u === uptae ? s.chipOn : s.chip}
                    onClick={() => setUptae(u)}
                  >
                    {u}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* ── 후보 ─────────────────────────────────────────────── */}
          <div className={s.block}>
            <h2 className={s.blockH}>
              <i>2</i> 후보를 넣으세요
            </h2>
            <p className={s.blockNote}>
              카드를 고른 다음 지도에서 그 자리를 찍으면 위치가 들어가요.
            </p>

            <div className={s.slots}>
              {slots.map((sl, i) => (
                <SlotCard
                  key={i}
                  slot={sl}
                  index={i}
                  active={i === active}
                  removable={slots.length > 1}
                  onActivate={() => setActive(i)}
                  onChange={(next) => patch(i, next)}
                  onRemove={() => {
                    setSlots((prev) => prev.filter((_, j) => j !== i));
                    setActive((a) => (a >= i && a > 0 ? a - 1 : a));
                  }}
                />
              ))}
            </div>

            {slots.length < MAX_CANDIDATES ? (
              <button
                className={s.addBtn}
                onClick={() => {
                  setSlots((prev) => [...prev, emptySlot(prev.length)]);
                  setActive(slots.length);
                }}
              >
                + 후보 추가 ({slots.length}/{MAX_CANDIDATES})
              </button>
            ) : null}
          </div>

          {/* ── 임차 기간 ─────────────────────────────────────────── */}
          <div className={s.block}>
            <h2 className={s.blockH}>
              <i>3</i> 몇 년 하실 생각인가요
            </h2>
            <p className={s.blockNote}>
              권리금을 이 기간에 나눠 담아요. 짧게 잡을수록 한 달 부담이 커지고, 순위가
              바뀌기도 해요.
            </p>
            <div className={s.leaseField}>
              <div className={s.leaseHead}>
                <span className={s.leaseLabel}>임차 기간</span>
                <strong>{leaseYears}년</strong>
              </div>
              <input
                className={s.leaseRange}
                type="range"
                min={LEASE_MIN}
                max={LEASE_MAX}
                step={1}
                value={leaseYears}
                aria-label="임차 기간(년)"
                onChange={(e) => setLeaseYears(Number(e.target.value))}
                style={{
                  background: `linear-gradient(to right, var(--fg-y) ${
                    ((leaseYears - LEASE_MIN) / (LEASE_MAX - LEASE_MIN)) * 100
                  }%, var(--fg-line2) 0)`,
                }}
              />
              <div className={s.leaseTicks}>
                <span>{LEASE_MIN}년</span>
                <span>{LEASE_MAX}년</span>
              </div>
            </div>
          </div>

          <button className={s.runBtn} disabled={!canCompare || compare.isPending} onClick={run}>
            {compare.isPending ? "계산 중…" : "다시 줄 세우기"}
          </button>
          {!canCompare ? (
            <p className={s.runHint}>
              업종을 고르고, 후보 <b>두 곳</b>에 위치와 보증금·월세·권리금을 넣어 주세요.
              한 곳만으로는 줄을 세울 수 없어요.
            </p>
          ) : droppedForCell.length > 0 ? (
            <p className={s.runHint}>
              {droppedForCell.map((sl) => sl.label).join("·")}는 지도에서 자리를 찍지 않아
              이번 비교에서 빠져요.
            </p>
          ) : null}
        </section>

        {/* ── 지도 ───────────────────────────────────────────────── */}
        <section className={s.mapWrap}>
          {uptae ? (
            <>
              <div className={s.mapHead}>
                <span>
                  <strong>{slots[active]?.label ?? "?"}</strong> 후보의 자리를 찍어 주세요
                </span>
                {/* S3 지도와 같은 조작 — 아는 동네 이름으로 날아간 다음 찍는다. */}
                <AreaPicker dark onPick={setJump} />
              </div>
              {seed.isPending ? (
                <div className={s.mapEmpty}>
                  <Loading label="지도를 열 자리를 찾는 중…" />
                </div>
              ) : seed.isError ? (
                <div className={s.mapEmpty}>
                  <ErrorState onRetry={() => seed.refetch()} detail={String(seed.error)} />
                </div>
              ) : focus === null ? (
                <div className={s.mapEmpty}>
                  이 업종은 채점된 자리가 없어서 지도를 열 수 없어요.
                </div>
              ) : (
              <div className={s.map}>
                <GridMap
                  uptae={uptae}
                  focus={focus}
                  candidateIds={slots.flatMap((sl) => (sl.cell ? [sl.cell.gridId] : []))}
                  selectedId={slots[active]?.cell?.gridId ?? null}
                  hoveredId={null}
                  onSelect={onPick}
                />
              </div>
              )}
              <p className={s.mapNote}>
                지도는 이 업종에서 가장 잘 나온 자리 근처에서 열려요. 원하는 자리로 옮겨서 찍으면
                돼요. 넓게 보면 칸이 사라지는데, 자리가 없어서가 아니라 한 번에 그릴 수 있는 칸
                수를 넘어서예요.
              </p>
            </>
          ) : (
            <div className={s.mapEmpty}>업종을 고르면 지도가 열려요.</div>
          )}
        </section>
      </main>

      {/* ── 결과 ─────────────────────────────────────────────────── */}
      {compare.isError ? (
        <div className={s.resultPad}>
          <ErrorState onRetry={run} detail={String(compare.error)} />
        </div>
      ) : compare.data ? (
        <Reversal r={compare.data} />
      ) : null}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   순위 역전 — 이 화면의 존재 이유
   ───────────────────────────────────────────────────────────────── */

const ROW_H = 62;

/** `rankMoved`는 서버 값 둘의 뺄셈이라 재계산이 아니라 표시 연산이다. */
type Labeled = CompareItem & { label: string; rankMoved: number };

function Reversal({ r }: { r: CompareResponse }) {
  const items: Labeled[] = r.items.map((it, i) => ({
    ...it,
    label: it.label ?? SLOT_LABELS[i] ?? String(i + 1),
    rankMoved: it.rentRank - it.teoRank,
  }));
  const byRent = [...items].sort((a, b) => a.rentRank - b.rentRank);
  const byTeo = [...items].sort((a, b) => a.teoRank - b.teoRank);
  const moved = items.some((it) => it.rankMoved !== 0);
  // 후보 전부의 매출이 동점이면 부담률로 줄 세울 수 없다 (같은 상권).
  const burdenComparable = items.length > 1 && items.some((it) => !it.revenueTied);
  const height = Math.max(byRent.length, byTeo.length) * ROW_H;
  // 서버가 실제로 쓴 상각 기간. 화면 선택값이 아니라 응답을 되읽어야, 요청이
  // 무시되거나 서버 기본값으로 떨어진 경우에도 각주가 사실을 말한다.
  const horizonMonths = items[0]?.paramsUsed?.horizonMonths ?? null;

  return (
    <section className={s.result}>
      <header className={s.resultHead}>
        <h2>{moved ? "순위가 뒤집혔어요" : "순위는 그대로예요"}</h2>
        <p>
          {moved
            ? "월세만 보고 고르면 다른 자리를 골랐을 거예요."
            : "이 후보들은 월세로 봐도, 실제로 나가는 돈으로 봐도 순서가 같아요."}
        </p>
      </header>

      <div className={s.slope} style={{ height }}>
        <div className={s.slopeCol}>
          <span className={s.slopeColH}>월세 기준</span>
          {byRent.map((it, i) => (
            <RankRow key={it.label} it={it} i={i} metric={man(it.monthlyRent)} side="left" />
          ))}
        </div>

        {/* 잇는 선이 교차하는 것 자체가 메시지다. */}
        {/* 높이를 인라인으로 못박는다. CSS 의 height:100% 는 SVG 가 replaced
            element 라 풀리고, 그러면 viewBox 비율로 폭×1.24 가 잡혀(실측 248px)
            선이 행 위치를 벗어나 아래 표까지 내려온다. */}
        <svg
          className={s.slopeLines}
          viewBox={`0 0 100 ${height}`}
          preserveAspectRatio="none"
          style={{ height }}
        >
          {items.map((it) => {
            const y1 = (it.rentRank - 1) * ROW_H + ROW_H / 2;
            const y2 = (it.teoRank - 1) * ROW_H + ROW_H / 2;
            return (
              <line
                key={it.label}
                x1="0"
                y1={y1}
                x2="100"
                y2={y2}
                className={it.rankMoved > 0 ? s.lineUp : it.rankMoved < 0 ? s.lineDown : s.lineFlat}
              />
            );
          })}
        </svg>

        <div className={s.slopeCol}>
          <span className={s.slopeColH}>실제로 나가는 돈 기준</span>
          {byTeo.map((it, i) => (
            <RankRow
              key={it.label}
              it={it}
              i={i}
              metric={man(it.effectiveCost)}
              side="right"
            />
          ))}
        </div>
      </div>

      {/* 상세 표 — 선이 말한 것을 숫자로 확인시킨다 */}
      <table className={s.table}>
        <thead>
          <tr>
            {/* 전부 응답의 cost 값이다. 입력값을 역산해 복원하지 않는다 —
                파생값에서 원금을 되짚으면 파라미터가 바뀌는 순간 거짓이 된다. */}
            <th>후보</th>
            <th>월 임대료</th>
            <th>보증금 이자</th>
            <th>권리금 손실분</th>
            <th>실질 월 점유비용</th>
            <th>부담률</th>
          </tr>
        </thead>
        <tbody>
          {byTeo.map((it) => (
            <tr key={it.label}>
              <td>
                <span className={s.tag}>{it.label}</span>
                {it.rankMoved !== 0 ? (
                  <em className={it.rankMoved > 0 ? s.moveUp : s.moveDown}>
                    {it.rankMoved > 0 ? "▲" : "▼"}
                    {Math.abs(it.rankMoved)}
                  </em>
                ) : null}
              </td>
              <td>{man(it.costBreakdown.rent)}</td>
              <td>{man(it.costBreakdown.depositOpportunity)}</td>
              <td>{man(it.costBreakdown.premiumAmortized)}</td>
              <td className={s.strongCell}>
                {man(it.effectiveCost)}
                {/* 대표값은 «권리금을 한 푼도 못 건진다»는 한 점이다. 서버가 함께
                    보내는 밴드는 회수·상각기간·이자율을 동시에 흔든 27조합의
                    5~95% 구간이라, 그 한 점이 얼마나 단단한지를 같은 칸에서 말한다. */}
                <em className={s.cellBand}>
                  {man(it.effectiveCostBand.low)}~{man(it.effectiveCostBand.high)}
                </em>
              </td>
              <td>
                {/* null은 «매출 근거 없음»이지 0이 아니다 */}
                {it.burdenRate !== null ? pct1(it.burdenRate) : <span className={s.none}>정보 없음</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={s.tableFoot}>
        보증금은 돌려받으니 이자만, 권리금은 못 건지는 몫만 비용으로 잡았어요.
        {/* 결과를 가장 크게 흔드는 값이라 각주가 아니라 결과 옆에 적는다. 화면에
            고른 기간이 아니라 서버가 실제로 쓴 값을 되읽어 쓴다. */}
        {horizonMonths !== null
          ? ` 권리금은 ${horizonMonths / 12}년에 나눠 담은 값이에요 — 기간을 바꾸면 순위가 달라질 수 있어요.`
          : ""}
      </p>

      {/* 이 화면이 산술에서 판단으로 넘어가는 지점. 밴드 폭 자체가 정보다 —
          좁으면 어떤 가정을 써도 같은 값이고, 넓으면 «고르기 어려운 자리»다.
          회수 축은 승계 모델(M2)이 격자별로 내는 값이라 자리마다 다르다. */}
      <div className={s.uncertainty}>
        <h3>가정을 흔들어도 그대로인가</h3>
        <ul>
          {byTeo.map((it) => {
            const width = it.effectiveCostBand.high - it.effectiveCostBand.low;
            const firm = width < it.effectiveCost * 0.05;
            return (
              <li key={it.label}>
                <span className={s.tag}>{it.label}</span>
                <b className={firm ? s.firm : s.shaky}>
                  {firm ? "거의 안 움직여요" : `${man(width)} 폭으로 움직여요`}
                </b>
                <span className={s.uncertaintyWhy}>
                  {firm
                    ? "권리금이 없거나 작아서, 몇 년을 하든 회수를 얼마나 하든 결과가 같아요."
                    : `권리금을 못 건지면 ${man(it.effectiveCostBand.high)}, 이 자리 승계 비율만큼 건지면 ${man(it.effectiveCostBand.low)}이에요.`}
                </span>
              </li>
            );
          })}
        </ul>
        <p className={s.uncertaintyNote}>
          {/* 승계확률의 뜻을 좁게 못박는다. 지불비율 원천이 없다는 사실을 빼면
              «권리금을 36% 돌려받는다»로 읽힌다 — 우리가 재지 않은 값이다. */}
          «승계 비율»은 그 자리에서 가게가 문을 닫은 뒤 다음 가게가 곧바로 들어온
          비율이에요. 인허가 이력으로 학습해 맞춰 본 값이고
          {byTeo.some((it) => it.successionProb > 0)
            ? ` (${byTeo.map((it) => `${it.label} ${pct0(it.successionProb)}`).join(" · ")})`
            : ""}
          , 권리금을 그만큼 돌려받는다는 뜻은 아니에요 — 얼마에 넘겼는지는 공개된
          기록이 없어요. 대표값은 <b>한 푼도 못 건진다</b>고 본 쪽입니다.
        </p>
      </div>

      {/* 부담률로 줄 세울 수 있는지 — 같은 상권이면 매출이 동점이라 못 한다 */}
      <p className={burdenComparable ? s.burdenOk : s.burdenNo}>
        {burdenComparable
          ? "후보들이 서로 다른 상권이라, 매출까지 반영한 부담률로도 순서가 달라질 수 있어요."
          : // 부담률 값 자체는 나온다(비용이 다르니까). 다만 매출이 동점이라
            // 부담률 순위가 비용 순위와 같아져 «새로 뒤집히는» 일이 없다.
            // "부담률을 안 냈다"고 쓰면 표에 보이는 값과 어긋난다.
            "후보들의 예상 매출이 같은 값이에요. 매출은 상권 단위라 같은 상권 안에서는 구분되지 않아요. 그래서 부담률 순서는 위 비용 순서와 같고, 여기서 한 번 더 뒤집히지는 않아요."}
      </p>
      {items[0] ? <p className={s.notice}>{items[0].notice}</p> : null}
    </section>
  );
}

function RankRow({
  it,
  i,
  metric,
  side,
}: {
  it: Labeled;
  i: number;
  metric: string;
  side: "left" | "right";
}) {
  return (
    <div className={side === "left" ? s.rankRowL : s.rankRowR} style={{ height: ROW_H }}>
      <span className={s.rankNum}>{i + 1}</span>
      <div className={s.rankBody}>
        <strong>{it.label}</strong>
        <em>{metric}</em>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   후보 카드
   ───────────────────────────────────────────────────────────────── */

function SlotCard({
  slot,
  index,
  active,
  removable,
  onActivate,
  onChange,
  onRemove,
}: {
  slot: Slot;
  index: number;
  active: boolean;
  removable: boolean;
  onActivate: () => void;
  onChange: (next: Partial<Slot>) => void;
  onRemove: () => void;
}) {
  return (
    <div className={active ? s.slotOn : s.slot} onFocusCapture={onActivate} onClick={onActivate}>
      <div className={s.slotHead}>
        <span className={s.slotTag}>{slot.label}</span>
        {slot.cell ? (
          <span className={s.slotPlace}>
            {slot.cell.grade}등급 자리
            {slot.cell.salesAvailable ? "" : " · 상권 밖"}
          </span>
        ) : (
          <span className={s.slotPlaceNone}>지도에서 자리를 찍어 주세요</span>
        )}
        {removable ? (
          <button
            className={s.slotDel}
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            aria-label={`후보 ${slot.label} 빼기`}
          >
            ✕
          </button>
        ) : null}
      </div>

      <div className={s.slotFields}>
        <Num label="보증금" value={slot.deposit} onChange={(v) => onChange({ deposit: v })} placeholder="5,000" />
        <Num label="월 임대료" value={slot.rentMonthly} onChange={(v) => onChange({ rentMonthly: v })} placeholder="250" />
        <Num label="권리금" value={slot.goodwill} onChange={(v) => onChange({ goodwill: v })} placeholder="없으면 0" />
        <Num
          label="면적"
          value={slot.areaM2}
          onChange={(v) => onChange({ areaM2: v })}
          unit="㎡"
          placeholder="66"
        />
        <Num
          label="층"
          value={slot.floor}
          onChange={(v) => onChange({ floor: v })}
          unit="층"
          placeholder="지하 -1"
          allowNegative
        />
      </div>
      <span className="sr-only">후보 {index + 1}</span>
    </div>
  );
}

function Num({
  label,
  value,
  onChange,
  placeholder,
  unit = "만원",
  allowNegative,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  placeholder: string;
  unit?: string;
  allowNegative?: boolean;
}) {
  return (
    <label className={s.num}>
      <span className={s.numLabel}>{label}</span>
      <span className={s.numInput}>
        <input
          type="number"
          min={allowNegative ? undefined : 0}
          value={value ?? ""}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        />
        <span className={s.numUnit}>{unit}</span>
      </span>
    </label>
  );
}
