import { useCallback, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { api } from "../api/client";
import type {
  CompareItem,
  CompareResponse,
  GridCell,
  Point,
  RunwayResponse,
} from "../api/types";
import AreaPicker from "../components/AreaPicker";
import GridMap from "../components/GridMap";
import { ErrorState, Loading } from "../components/states";
import { man, pct0, pct1, uptaeLabel } from "../lib/format";
import { parseNum } from "../lib/guard";
import { useSearch } from "../state/search";
import s from "./S5Compare.module.css";

// 후보를 이미 손에 쥔 사람을 위한 입구다. «어디가 좋아?»가 아니라 «여기
// 계약해도 되나요»를 묻는 사람이라, 이 화면은 탐색이 아니라 판정이다.
//
// 증명할 것은 하나: 정렬 기준을 바꾸면 순위가 실제로 뒤집힌다. 표를 둘 놓으면
// «숫자가 다르네»로 끝나서, 두 순위를 선으로 이어 교차를 눈에 보이게 그린다.
//
// 위치는 지도 클릭으로만 잡는다. 번지 검색은 지오코딩 키가 없어 못 한다. 아는
// 동네로 날아가는 것까지는 /api/areas 로 되므로 지도 머리에 지역 찾기를 둔다.

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

/** 예산 버티기 — 후보별 runway 응답. null 은 그 후보의 계산 실패(보이게 실패). */
interface RunwayRow {
  label: string;
  result: RunwayResponse | null;
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

  // 예산은 사람의 것이라 후보 공용이고, S4 버티기 카드와 같은 값을 공유한다.
  // 그 외 초기투자(인테리어 등)는 이 화면 전용 — 모든 후보에 같이 더한다.
  const search = useSearch();
  const budget = search.budget;
  const [extraUpfront, setExtraUpfront] = useState<number | null>(null);
  // rows 는 자기 요청 키와 함께 저장한다 — 늦게 도착한 이전 예산의 응답이
  // 현재 결과를 덮어쓰는 레이스를 키 대조로 끊는다 (compare 의 ranKey 게이트는
  // compare 결과만 지킨다).
  const [runwayRows, setRunwayRows] = useState<{ key: string; rows: RunwayRow[] } | null>(null);
  const [runwayPending, setRunwayPending] = useState(false);
  const latestRunwayKey = useRef<string | null>(null);

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

  // label을 실어 보내면 서버가 그대로 되싣는다. 순서에 기대지 않는 이유는
  // 같은 격자에 후보가 둘일 수 있어서다(같은 건물 1층/2층) — gridId로는
  // 후보를 구분할 수 없다.
  const payload = {
    uptae: uptae!,
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
  };
  // 결과가 어떤 조건에서 나왔는지 붙들어 둔다. 이게 없으면 업종·기간·금액을
  // 바꾼 뒤에도 이전 결과가 그대로 붙어 있어, 사용자는 그것을 지금 조건의
  // 답으로 읽는다. 보낸 것과 같은 것에서만 결과를 보여 준다. 예산·공통
  // 초기투자도 결과(버티는 기간)를 바꾸므로 같은 키에 묶는다.
  const requestKey = JSON.stringify({ payload, budget, extraUpfront });
  const [ranKey, setRanKey] = useState<string | null>(null);

  const run = () => {
    if (!canCompare) return;
    setRanKey(requestKey);
    compare.mutate(payload);
    // 버티는 기간은 비교와 별개 축이라 실패해도 비교를 막지 않는다. 후보별로
    // 실패를 따로 담아 «그 후보만 계산 못 했다»를 보이게 남긴다.
    if (budget !== null) {
      const key = requestKey;
      latestRunwayKey.current = key;
      setRunwayPending(true);
      setRunwayRows(null);
      Promise.all(
        ready.map((sl) =>
          api
            .runway({
              gridId: sl.cell!.gridId,
              uptae: uptae!,
              budget,
              upfront: sl.deposit! + sl.goodwill! + (extraUpfront ?? 0),
              rentMonthly: sl.rentMonthly!,
            })
            .then(
              (result): RunwayRow => ({ label: sl.label, result }),
              (): RunwayRow => ({ label: sl.label, result: null }),
            ),
        ),
      ).then((rows) => {
        if (latestRunwayKey.current !== key) return; // 이미 다른 실행이 대체
        setRunwayRows({ key, rows });
        setRunwayPending(false);
      });
    } else {
      latestRunwayKey.current = null;
      setRunwayRows(null);
      setRunwayPending(false);
    }
  };

  // 업종이 바뀌면 찍어 둔 자리의 등급은 이전 업종의 값이다. 금액은 업종과
  // 무관하니 남기고, 등급을 달고 있는 자리만 비운다.
  const pickUptae = (next: string) => {
    if (next === uptae) return;
    setUptae(next);
    setSlots((prev) => prev.map((sl) => (sl.cell ? { ...sl, cell: null } : sl)));
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
        {/* 최대 세 곳이라는 것은 «+ 후보 추가 (2/3)» 버튼이 스스로 말한다. */}
        <p className={s.heroSub}>
          보증금과 권리금까지 한 달치로 바꿔서 다시 줄을 세워 드려요.
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
                    onClick={() => pickUptae(u)}
                  >
                    {uptaeLabel(u)}
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

          {/* ── 예산 (선택) ───────────────────────────────────────── */}
          <div className={s.block}>
            <h2 className={s.blockH}>
              <i>4</i> 예산도 넣어볼까요
            </h2>
            <p className={s.blockNote}>
              선택이에요. 넣으면 계약하고 남는 돈으로 각 자리에서 몇 개월
              버티는지도 같이 계산해요.
            </p>
            <div className={s.budgetRow}>
              <Num
                label="총 예산"
                value={budget}
                onChange={(v) => search.set({ budget: v })}
                placeholder="예: 15,000"
              />
              <Num
                label="그 외 초기투자"
                value={extraUpfront}
                onChange={setExtraUpfront}
                placeholder="인테리어 등, 없으면 비움"
              />
            </div>
          </div>

          <button className={s.runBtn} disabled={!canCompare || compare.isPending} onClick={run}>
            {compare.isPending ? "계산 중…" : "다시 줄 세우기"}
          </button>
          {/* «업종을 고르세요»·«후보를 넣으세요» 는 위 단계 제목이 이미 한 말이다.
              여기서는 왜 한 곳으로는 안 되는지만 남긴다. */}
          {!canCompare ? (
            <p className={s.runHint}>
              후보 <b>두 곳</b>은 채워야 줄을 세울 수 있어요. 위치와 보증금·월세·권리금이
              모두 필요해요.
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
      ) : compare.data && ranKey === requestKey ? (
        <Reversal
          r={compare.data}
          runway={
            budget !== null
              ? {
                  budget,
                  extraUpfront: extraUpfront ?? 0,
                  pending: runwayPending,
                  rows: runwayRows?.key === requestKey ? runwayRows.rows : null,
                }
              : null
          }
        />
      ) : compare.data ? (
        <div className={s.resultPad}>
          <p className={s.stale}>
            조건이 바뀌었어요. 아래 결과는 바꾸기 전 것이라 지웠어요 — 다시
            계산해 주세요.
          </p>
        </div>
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

interface RunwayStripData {
  budget: number;
  extraUpfront: number;
  pending: boolean;
  rows: RunwayRow[] | null;
}

function Reversal({ r, runway }: { r: CompareResponse; runway: RunwayStripData | null }) {
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
  // 매출 없는 상권 후보는 서버 정렬 규칙상 맨 뒤로 간다 — 측정이 아니라 규칙이다.
  const hasUnmeasured = items.some((it) => it.burdenRate === null);
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
            // 매출 없는 상권의 하락은 잰 값이 아니라 정렬 규칙이므로
            // 색으로 나쁨을 주장하지 않는다.
            const lineClass =
              it.burdenRate === null
                ? s.lineFlat
                : it.rankMoved > 0
                  ? s.lineUp
                  : it.rankMoved < 0
                    ? s.lineDown
                    : s.lineFlat;
            return (
              <line
                key={it.label}
                x1="0"
                y1={y1}
                x2="100"
                y2={y2}
                className={lineClass}
              />
            );
          })}
        </svg>

        <div className={s.slopeCol}>
          {/* 교차 상권이면 오른쪽 순위는 비용이 아니라 부담률이 먼저다 —
              비용 기준이라고 쓰면 비싼 후보가 1위인 화면이 거짓말이 된다 */}
          <span className={s.slopeColH}>
            {burdenComparable ? "매출 부담까지 반영한 순위" : "실제로 나가는 돈 기준"}
          </span>
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
                {/* 매출 없는 상권의 ▼는 «실제로 더 나쁨»이라는, 재지 않은 주장이 된다 */}
                {it.rankMoved !== 0 && it.burdenRate !== null ? (
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
                {/* 끝값을 특정 가정에 귀속하지 않는다 — 밴드는 회수·상각기간·
                    이자율을 함께 흔든 5~95% 구간이라, «못 건지면 = 높은 쪽» 은
                    같은 화면의 대표값(전액 손실 가정)과 다른 숫자를 말하게 된다. */}
                <span className={s.uncertaintyWhy}>
                  {firm
                    ? "권리금이 없거나 작아서, 몇 년을 하든 회수를 얼마나 하든 결과가 같아요."
                    : `권리금 회수·상각 기간 ±1년·이자율 ±1%p를 함께 흔들면 ${man(it.effectiveCostBand.low)}~${man(it.effectiveCostBand.high)} 사이에서 움직여요.`}
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
          {/* null 은 «계산할 기록이 없다»이지 0% 가 아니다. 걸러 내지 않으면
              pct0(null) 이 «0%» 를 찍어 없는 값을 잰 값처럼 만든다. 반대로
              측정된 0 은 잰 값이므로 그대로 낸다. */}
          {(() => {
            const known = byTeo.filter((it) => it.successionProb !== null);
            return known.length
              ? ` (${known.map((it) => `${it.label} ${pct0(it.successionProb!)}`).join(" · ")})`
              : "";
          })()}
          , 권리금을 그만큼 돌려받는다는 뜻은 아니에요 — 얼마에 넘겼는지는 공개된
          기록이 없어요. 대표값은 <b>한 푼도 못 건진다</b>고 본 쪽입니다.
        </p>
      </div>

      {/* 예산 버티기 — 순위와 별개 축. 부담률은 좋은데 운영자금이 없는 후보를
          잡는 장치라, 정렬에는 손대지 않고 후보별 판정만 늘어놓는다. */}
      {runway ? (
        <div className={s.uncertainty}>
          <h3>예산 {man(runway.budget)}으로 버티면</h3>
          {runway.pending ? (
            <Loading label="버티는 기간 계산 중…" />
          ) : runway.rows ? (
            <ul>
              {byTeo.map((it) => {
                const row = runway.rows!.find((x) => x.label === it.label);
                if (!row) return null;
                return (
                  <li key={it.label}>
                    <span className={s.tag}>{it.label}</span>
                    <RunwayVerdict result={row.result} />
                  </li>
                );
              })}
            </ul>
          ) : null}
          <p className={s.uncertaintyNote}>
            초기투자는 보증금+권리금
            {runway.extraUpfront > 0 ? `+공통 초기투자 ${man(runway.extraUpfront)}` : ""}
            으로 잡았어요. 매출은 각 자리 주변 상권의 같은 업종 평균(없으면 서울
            평균), 마진율은 기본값, 매출이 자리 잡는 기간은 6개월로 가정했어요 —
            자리 상세의 버티기 카드에서 조건을 바꿔 볼 수 있어요.
          </p>
        </div>
      ) : null}

      {/* 부담률로 줄 세울 수 있는지 — 같은 상권이면 매출이 동점이라 못 한다 */}
      <p className={burdenComparable ? s.burdenOk : s.burdenNo}>
        {burdenComparable
          ? // 오른쪽 순위가 이미 부담률 순서라는 사실을 말한다 — "달라질 수
            // 있어요"는 표시된 순서가 비용 순서라는 오독을 남긴다.
            "후보들이 서로 다른 상권이라, 오른쪽 순위는 실질 비용에 그 상권 매출 부담까지 반영한 순서예요. 금액만 비교하려면 표의 «실질 월 점유비용»을 보세요."
          : // 부담률 값 자체는 나온다(비용이 다르니까). 다만 매출이 동점이라
            // 부담률 순위가 비용 순위와 같아져 «새로 뒤집히는» 일이 없다.
            // "부담률을 안 냈다"고 쓰면 표에 보이는 값과 어긋난다.
            "후보들의 예상 매출이 같은 값이에요. 매출은 상권 단위라 같은 상권 안에서는 구분되지 않아요. 그래서 부담률 순서는 위 비용 순서와 같고, 여기서 한 번 더 뒤집히지는 않아요."}
      </p>
      {hasUnmeasured ? (
        <p className={s.burdenNo}>
          매출 정보가 없는 상권의 후보는 부담을 잴 수 없어서 순위 맨 뒤에 있어요.
          자리가 나쁘다는 뜻이 아니라 잴 수 없다는 뜻이에요 — 금액은 표의 실질 월
          점유비용으로 비교하세요.
        </p>
      ) : null}
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

/** 후보 한 곳의 버티기 판정 한 줄. null = 그 후보만 계산 실패 — 숨기지 않는다. */
function RunwayVerdict({ result }: { result: RunwayResponse | null }) {
  if (result === null) {
    return (
      <b className={s.rwFail}>계산하지 못했어요 — «다시 줄 세우기»로 다시 시도해 주세요.</b>
    );
  }
  switch (result.level) {
    case "IMPOSSIBLE":
      return (
        <>
          <b className={s.rwBad}>계약 자체가 어려워요</b>
          <span className={s.uncertaintyWhy}>
            초기투자가 예산보다 {man(-result.reserve)} 많아요.
          </span>
        </>
      );
    case "DANGER":
      return (
        <>
          <b className={s.rwBad}>
            {result.depletionMonth !== null
              ? `개업 ${result.depletionMonth}개월차에 돈이 바닥나요`
              : "초기 골짜기를 못 넘어요"}
          </b>
          <span className={s.uncertaintyWhy}>
            계약하고 남는 돈 {man(result.reserve)}으로는 부족해요{revenueNote(result)}.
          </span>
        </>
      );
    case "WARN":
      // 지평 안에 흑자 전환이 없으면(서버가 OK 를 강등한 케이스) «여유가
      // 없다»가 아니라 «매달 적자»가 사실이다 — 다른 문장을 쓴다.
      return result.breakevenMonth === null ? (
        <>
          <b className={s.shaky}>버텨도 매달 적자예요</b>
          <span className={s.uncertaintyWhy}>
            {result.horizonMonths}개월 안에 월 흑자가 안 와요{revenueNote(result)}.
          </span>
        </>
      ) : (
        <>
          <b className={s.shaky}>버티지만 여유가 거의 없어요</b>
          <span className={s.uncertaintyWhy}>
            매출이 예상보다 늦게 오르면 위험해요 — 남는 돈 {man(result.reserve)}
            {revenueNote(result)}.
          </span>
        </>
      );
    default:
      return (
        <>
          <b className={s.firm}>초기 골짜기를 넘을 돈이 확보돼요</b>
          <span className={s.uncertaintyWhy}>
            계약하고 남는 돈이 {man(result.reserve)}이라 여유가 있어요
            {revenueNote(result)}.
          </span>
        </>
      );
  }
}

/** 기본값 매출로 판정했으면 그 금액을 판정 옆에 그대로 밝힌다. */
function revenueNote(result: RunwayResponse): string {
  return result.revenueSource === "user_input"
    ? ""
    : ` (매출은 월 ${man(result.revenueMonthly)} 가정)`;
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
  // 후보가 둘 이상이면 «6등급 자리» 만으로는 어느 게 어디였는지 알 수 없다.
  // 지도 말풍선과 같은 캐시 키라, 찍는 순간 이미 받아둔 값이 그대로 온다.
  const addr = useQuery({
    queryKey: ["gridAddress", slot.cell?.gridId],
    queryFn: () => api.gridAddress(slot.cell!.gridId),
    enabled: slot.cell !== null,
    staleTime: Infinity,
  });

  return (
    <div className={active ? s.slotOn : s.slot} onFocusCapture={onActivate} onClick={onActivate}>
      <div className={s.slotHead}>
        <span className={s.slotTag}>{slot.label}</span>
        {slot.cell ? (
          <span className={s.slotPlace}>
            {addr.data?.label ? <b className={s.slotAddr}>{addr.data.label}</b> : null}
            <span className={s.slotGrade}>
              {slot.cell.grade}등급 자리
              {slot.cell.salesAvailable ? "" : " · 상권 밖"}
            </span>
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
          min={allowNegative ? -10 : 0}
          value={value ?? ""}
          placeholder={placeholder}
          onChange={(e) =>
            onChange(parseNum(e.target.value, allowNegative ? { min: -10, max: 200 } : {}))
          }
        />
        <span className={s.numUnit}>{unit}</span>
      </span>
    </label>
  );
}
