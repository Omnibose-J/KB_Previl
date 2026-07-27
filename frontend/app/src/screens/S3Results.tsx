import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { api } from "../api/client";
import CandidateCard from "../components/CandidateCard";
import CaveatStrip from "../components/CaveatStrip";
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

  // What-if 초기화 restores the conditions this screen was entered with.
  const entry = useRef({ uptae, districts, rentMonthly });

  const q = useQuery({
    queryKey: ["recommend", uptae, districts],
    queryFn: () => api.recommend(uptae!, districts),
    enabled: uptae !== null,
  });

  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });

  const candidateIds = useMemo(() => q.data?.items.map((c) => c.gridId) ?? [], [q.data]);
  const top = q.data?.items[0];
  useEffect(() => {
    if (top) {
      setFocus(top.center);
      setSelectedId((cur) => cur ?? top.gridId);
    }
  }, [top]);

  const pins: MapPin[] = useMemo(
    () =>
      (q.data?.items ?? []).slice(0, 3).map((c, i) => ({
        id: c.gridId,
        rank: i + 1,
        label: c.admDong ?? c.gridId,
        center: c.center,
      })),
    [q.data],
  );

  const select = (cell: { gridId: string; center: Point }) => {
    setSelectedId(cell.gridId);
    setFocus(cell.center);
  };

  if (!uptae) {
    return (
      <div className={s.page}>
        <Nav step={2} onHome={() => go({ name: "landing" })} />
        <main className={s.guard}>
          <p>업종을 먼저 골라주세요.</p>
          <button className={s.guardBtn} onClick={() => go({ name: "input" })}>
            조건 입력으로
          </button>
        </main>
      </div>
    );
  }

  const items = q.data?.items ?? [];
  const verified = uniqueDongs(items.filter((c) => c.signal === "verified"));
  const overheated = uniqueDongs(items.filter((c) => c.signal === "overheated"));
  const partialCount = items.filter((c) => c.confidence === "partial").length;

  return (
    <div className={s.page}>
      <Nav
        step={3}
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
              <h1 className={s.rankTitle}>
                {q.data ? `추천 후보 ${int(q.data.count)}곳` : "추천 후보"}
              </h1>
              {q.data ? (
                <p className={s.rankSub}>
                  {q.data.inScope === q.data.totalGrids
                    ? `서울 전역 ${int(q.data.totalGrids)}개 격자를 등급순으로 추렸습니다`
                    : `서울 ${int(q.data.totalGrids)}개 격자 중 범위 안 ${int(q.data.inScope)}개를 등급순으로 추렸습니다`}
                </p>
              ) : null}
            </div>
            <span className={s.sort}>등급순 ▾</span>
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
              <label className={s.wCtl}>
                <span className={s.wTitle}>업종 변경</span>
                <select
                  className={s.wSelect}
                  value={uptae}
                  onChange={(e) => search.set({ uptae: e.target.value })}
                >
                  {(meta.data?.uptae ?? [uptae]).map((u) => (
                    <option key={u} value={u}>
                      {u}
                    </option>
                  ))}
                </select>
                <span className={s.wSub}>12개 업태 재분석</span>
              </label>
              <button
                className={s.wCtl}
                disabled={districts.length === 0}
                onClick={() => search.set({ districts: [] })}
              >
                <span className={s.wTitle}>범위 확대</span>
                <span className={s.wSub}>{districts.length === 0 ? "이미 서울 전역" : "서울 전역으로"}</span>
              </button>
              <label className={s.wCtl}>
                <span className={s.wTitle}>월 임대료</span>
                <span className={s.wInputRow}>
                  <input
                    className={s.wInput}
                    type="number"
                    min={0}
                    placeholder="미입력"
                    value={rentMonthly ?? ""}
                    onChange={(e) =>
                      search.set({ rentMonthly: e.target.value === "" ? null : Number(e.target.value) })
                    }
                  />
                  <span>만</span>
                </span>
                <span className={s.wSub}>손익 계산에 반영</span>
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
                  rentMonthly={rentMonthly}
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
            <h2 className={s.mapTitle}>입지 등급 히트맵</h2>
            <div className={s.tabs}>
              <button className={s.tabOn}>입지 등급</button>
              <button className={s.tab} disabled title="P1 준비 중 — 격자 응답에 경쟁 지표가 실리면 열립니다">
                경쟁 밀도
              </button>
              <button className={s.tab} disabled title="P1 준비 중">
                지역 생존율
              </button>
              <button className={s.tab} disabled title="P1 준비 중 (행정동 단위)">
                수요
              </button>
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
            />
          </div>
          <div className={s.insights}>
            <div className={s.insGreen}>
              <strong>검증된 자리</strong>
              <span>{verified.length > 0 ? verified.join(" · ") : "신호 산출 대기 (레인 A)"}</span>
            </div>
            <div className={s.insOrange}>
              <strong>과열 신호</strong>
              <span>{overheated.length > 0 ? overheated.join(" · ") : "감지되지 않음"}</span>
            </div>
            <div className={s.insGray}>
              <strong>상권 밖</strong>
              <span>{partialCount > 0 ? `부분 데이터 ${int(partialCount)}곳` : "후보 전원 상권 안"}</span>
            </div>
          </div>
        </aside>
      </main>

      <CaveatStrip />
    </div>
  );
}

function uniqueDongs(items: { admDong: string | null }[]): string[] {
  return [...new Set(items.map((c) => c.admDong).filter((d): d is string => d !== null))].slice(0, 3);
}
