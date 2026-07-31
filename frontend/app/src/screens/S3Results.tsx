import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { api } from "../api/client";
import { isRecommendable } from "../lib/grade";
import CandidateCard from "../components/CandidateCard";
import CaveatStrip from "../components/CaveatStrip";
import Dropdown from "../components/Dropdown";
import GridMap, { type MapPin } from "../components/GridMap";
import Nav from "../components/Nav";
import { Empty, ErrorState, Loading } from "../components/states";
import type { Point } from "../api/types";
import { int } from "../lib/format";
import { useSearch } from "../state/search";
import s from "./S3Results.module.css";

// S3, rebuilt against figma-snapshot S3: 600px ranking column (head → What-if
// dark panel → cards) + map panel (tabs → canvas → insights strip).
// The What-if controls are REAL: they mutate the shared search state and the
// recommend query refetches — no "+18곳" preview deltas are ever fabricated.
// Extra map tabs (경쟁·지역 생존율·수요) have no /grids payload yet, so they
// render disabled with an explicit 준비 중 label rather than pretending.

export default function S3Results({ go }: { go: (s: Screen) => void }) {
  const search = useSearch();
  const { uptae, districts, rentMonthly } = search;
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focus, setFocus] = useState<Point | null>(null);
  // 항상 새 배열로 넘긴다. 같은 좌표를 같은 참조로 다시 넣으면 React 가 상태
  // 갱신을 건너뛰고 GridMap 의 flyTo 이펙트가 돌지 않는다 — 지도를 손으로
  // 옮긴 뒤 같은 후보를 다시 눌러도 되돌아오지 않는 상태가 된다.
  const focusOn = (center: Point) => setFocus([center[0], center[1]]);

  // What-if 초기화 restores the conditions this screen was entered with.
  const entry = useRef({ uptae, districts, rentMonthly });

  const q = useQuery({
    queryKey: ["recommend", uptae, districts],
    queryFn: () => api.recommend(uptae!, districts),
    enabled: uptae !== null,
  });

  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });

  // 지역 찾기: 추천 범위를 바꾸지 않고 지도만 옮긴다. 범위를 좁히는 조작은
  // 자치구 필터(S2)가 이미 하고 있어서, 여기서 또 좁히면 둘이 어긋난다.
  const areas = useQuery({ queryKey: ["areas"], queryFn: api.areas });
  const [areaKey, setAreaKey] = useState<string | null>(null);
  const areaOptions = useMemo(
    () =>
      (areas.data?.items ?? []).map((a) => {
        const name = `${a.district} ${a.admDong}`;
        return { value: name, label: name };
      }),
    [areas.data],
  );
  const goToArea = (name: string) => {
    const hit = areas.data?.items.find((a) => `${a.district} ${a.admDong}` === name);
    if (!hit) return;
    setAreaKey(name);
    focusOn(hit.center);
  };

  // Threshold cut (lib/grade.ts isRecommendable): grade-1 cells only, so a
  // small scope shows its 3 real candidates instead of 20 padded ones.
  const items = useMemo(() => (q.data?.items ?? []).filter(isRecommendable), [q.data]);
  const candidateIds = useMemo(() => items.map((c) => c.gridId), [items]);
  const top = items[0];
  const topId = top?.gridId;
  useEffect(() => {
    if (top) {
      focusOn(top.center);
      setSelectedId((cur) => cur ?? top.gridId);
    }
    // Key on the id, not the object: a refetch returning the same top grid
    // must not re-fly and yank the user's viewport.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topId]);

  // What-if 업종 변경: the old selection belongs to another ranking.
  useEffect(() => {
    setSelectedId(null);
  }, [uptae]);

  const pins: MapPin[] = useMemo(
    () =>
      items.slice(0, 3).map((c, i) => ({
        id: c.gridId,
        rank: i + 1,
        label: c.admDong ?? c.gridId,
        center: c.center,
      })),
    [items],
  );

  const select = (cell: { gridId: string; center: Point }) => {
    setSelectedId(cell.gridId);
    focusOn(cell.center);
  };

  if (!uptae) {
    return (
      <div className={s.page}>
        <Nav onHome={() => go({ name: "landing" })} />
        <main className={s.guard}>
          <p>업종을 먼저 골라주세요.</p>
          <button className={s.guardBtn} onClick={() => go({ name: "input" })}>
            조건 입력으로
          </button>
        </main>
      </div>
    );
  }

  const partialCount = items.filter((c) => c.confidence === "partial").length;

  return (
    <div className={s.page}>
      <Nav
        onHome={() => go({ name: "landing" })}
        center={
          <div className={s.condPill}>
            <span>{uptae}</span>
            <i>·</i>
            <span>{rentMonthly === null ? "임대료 미입력" : `월 ${int(rentMonthly)}만`}</span>
            <i>·</i>
            <span>{districts.length === 0 ? "서울 전역" : `${districts.length}개 자치구`}</span>
            <button onClick={() => go({ name: "input" })}>조건 수정</button>
          </div>
        }
      />

      <main className={s.body}>
        {/* ── ranking column ─────────────────────────────────────────── */}
        <section className={s.ranking}>
          <header className={s.rankHead}>
            <div>
              {/* cap 20 (client top) + grade-1 threshold — the shown count is
                  the cells that pass the bar, not a padded page. */}
              <h1 className={s.rankTitle}>
                {q.data ? `추천 상위 ${int(items.length)}곳` : "추천 후보"}
              </h1>
              {q.data ? (
                <>
                  <p className={s.rankSub}>
                    {q.data.inScope === q.data.totalGrids
                      ? `서울 전체 ${int(q.data.totalGrids)}곳 중에서 골랐어요`
                      : `고른 동네의 ${int(q.data.inScope)}곳 중에서 골랐어요`}
                  </p>
                  {/* 순서는 등급인데 카드의 큰 숫자는 자리별 주변 기록이라, 1위가
                      2위보다 낮은 %로 보이는 일이 생긴다. 값을 바꾸는 대신 무엇이
                      순서를 정했는지 밝힌다 — 등급 실측치를 카드에 크게 넣는 길은
                      24장이 같은 숫자가 되어 이미 접었다(CandidateCard 주석). */}
                  <p className={s.rankNote}>
                    등급이 높은 순이에요 · 옆의 %는 자리마다 다른 주변 기록이라 순서와 다를 수 있어요
                  </p>
                </>
              ) : null}
            </div>
          </header>

          {/* What-if — every control performs the real mutation it names. */}
          <div className={s.whatif}>
            <div className={s.whatifHead}>
              <strong>What-if</strong>
              <button
                className={s.reset}
                onClick={() => {
                  search.set({
                    uptae: entry.current.uptae,
                    districts: entry.current.districts,
                    rentMonthly: entry.current.rentMonthly,
                  });
                }}
              >
                초기화
              </button>
            </div>
            <div className={s.whatifRow}>
              <div className={s.wCtl}>
                <span className={s.wTitle}>업종 변경</span>
                {/* No [uptae] fallback: a meta failure must look failed, not
                    like a working 1-option control (fail-loud rule). */}
                <Dropdown
                  dark
                  options={(meta.data?.uptae ?? []).map((u) => ({ value: u, label: u }))}
                  value={uptae}
                  display={uptae}
                  placeholder="업태"
                  emptyNote={meta.isError ? "목록을 불러오지 못했습니다" : "불러오는 중…"}
                  onSelect={(v) => search.set({ uptae: v })}
                />
                <span className={s.wSub}>바꾸면 바로 다시 추천해요</span>
              </div>
              <button
                className={s.wCtl}
                disabled={districts.length === 0}
                onClick={() => search.set({ districts: [] })}
              >
                <span className={s.wTitle}>범위 확대</span>
                <span className={s.wSub}>{districts.length === 0 ? "이미 서울 전체를 보고 있어요" : "서울 전체로 넓혀요"}</span>
              </button>
              <label className={s.wCtl}>
                <span className={s.wTitle}>월 임대료</span>
                <span className={s.wInputRow}>
                  <input
                    className={s.wInput}
                    type="number"
                    min={0}
                    placeholder="예: 250"
                    value={rentMonthly ?? ""}
                    onChange={(e) =>
                      search.set({ rentMonthly: e.target.value === "" ? null : Number(e.target.value) })
                    }
                  />
                  <span>만</span>
                </span>
                <span className={s.wSub}>손익 계산에 반영돼요</span>
              </label>
            </div>
          </div>

          {q.isPending ? <Loading /> : null}
          {q.isError ? <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} /> : null}
          {q.data && items.length === 0 ? <Empty /> : null}
          {items.length > 0 ? (
            <ul className={s.list}>
              {items.map((cell, i) => (
                <CandidateCard
                  key={cell.gridId}
                  rank={i + 1}
                  cell={cell}
                  selected={selectedId === cell.gridId}
                  onHover={setHoveredId}
                  onSelect={() => select(cell)}
                  onOpen={() => go({ name: "detail", gridId: cell.gridId, from: "results" })}
                />
              ))}
            </ul>
          ) : null}
        </section>

        {/* ── map panel ──────────────────────────────────────────────── */}
        <aside className={s.mapPanel}>
          <header className={s.mapHead}>
            <h2 className={s.mapTitle}>자리 등급 지도</h2>
            {/* 100m 칸만 깔린 지도에서는 «여기가 어디냐» 를 알 길이 없다. 동
                이름으로 날아가고(여기), 칸을 짚으면 번지를 답한다(GridMap 말풍선).
                이 자리에 있던 «자리 등급» 탭은 제목과 같은 말이라 뺐다 —
                하나뿐인 탭은 고를 것이 없어 조작이 아니라 딱지다. */}
            <div className={s.areaPick}>
              <Dropdown
                compact
                searchable
                options={areaOptions}
                value={areaKey}
                placeholder="지역 찾기"
                searchPlaceholder="동 이름으로 찾기"
                emptyNote={areas.isError ? "목록을 불러오지 못했습니다" : "불러오는 중…"}
                onSelect={goToArea}
              />
            </div>
          </header>
          <div className={s.mapBox}>
            <GridMap
              uptae={uptae}
              focus={focus}
              candidateIds={candidateIds}
              pins={pins}
              selectedId={selectedId}
              hoveredId={hoveredId}
              onSelect={(cell) => setSelectedId(cell.gridId)}
              onOpenDetail={(cell) =>
                // Diagnosis mode (ui-spec §2 B-모드): ANY scored cell opens its
                // report; only ranked candidates read as "추천 n위".
                go({
                  name: "detail",
                  gridId: cell.gridId,
                  from: candidateIds.includes(cell.gridId) ? "results" : "diagnosis",
                })
              }
            />
          </div>
          {/* Only a live fact earns a row here — the signal rows return when
              lane A ships the verdict column. */}
          {partialCount > 0 ? (
            <div className={s.insights}>
              <div className={s.insGray}>
                <strong>참고</strong>
                <span>주변 매출 기록이 없는 자리가 {int(partialCount)}곳 있어요</span>
              </div>
            </div>
          ) : null}
        </aside>
      </main>

      <CaveatStrip />
    </div>
  );
}
