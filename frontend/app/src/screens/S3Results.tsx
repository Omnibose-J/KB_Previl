import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { api } from "../api/client";
import CandidateCard from "../components/CandidateCard";
import CaveatStrip from "../components/CaveatStrip";
import GridMap from "../components/GridMap";
import Nav from "../components/Nav";
import { Empty, ErrorState, Loading } from "../components/states";
import type { Point } from "../api/types";
import { int } from "../lib/format";
import { useSearch } from "../state/search";
import s from "./S3Results.module.css";
import ui from "../styles/ui.module.css";

// S3 결과 — spec: ui-spec.md §3-S3 (P0: 지도 등급 탭 + 목록 + 한계 스트립).
// The map leads and the list supports (§0 원칙 4); hover syncs both ways.
// Out of P0 and deliberately absent: What-if 패널, 경쟁/지역 생존율/수요 탭,
// 비교함, 정렬 토글. A tab that does not query anything is a mockup.
export default function S3Results({ go }: { go: (s: Screen) => void }) {
  const { uptae, districts } = useSearch();
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focus, setFocus] = useState<Point | null>(null);

  const q = useQuery({
    queryKey: ["recommend", uptae, districts],
    queryFn: () => api.recommend(uptae!, districts),
    enabled: uptae !== null,
  });

  const candidateIds = useMemo(() => q.data?.items.map((c) => c.gridId) ?? [], [q.data]);
  const top = q.data?.items[0];
  useEffect(() => {
    if (top) setFocus(top.center);
  }, [top]);

  const select = (cell: { gridId: string; center: Point }) => {
    setSelectedId(cell.gridId);
    setFocus(cell.center);
  };

  if (!uptae) {
    return (
      <>
        <Nav step={2} onHome={() => go({ name: "landing" })} />
        <main className={s.guard}>
          <p>업종을 먼저 골라주세요.</p>
          <button className={ui.btnPrimary} onClick={() => go({ name: "input" })}>
            조건 입력으로
          </button>
        </main>
      </>
    );
  }

  return (
    <>
      <Nav
        step={3}
        onHome={() => go({ name: "landing" })}
        right={
          <>
            <span className={s.conditions}>
              {uptae} · {districts.length === 0 ? "서울 전역" : `${districts.length}개 자치구`}
            </span>
            <button className={ui.btn} onClick={() => go({ name: "input" })}>
              조건 수정
            </button>
          </>
        }
      />

      <main className={s.body}>
        <section className={s.ranking}>
          <header className={s.rankHead}>
            <h1 className={s.rankTitle}>
              {q.data ? `추천 후보 ${int(q.data.items.length)}곳` : "추천 후보"}
            </h1>
            {/* Funnel numbers are API values — the mockup's 12,480→842→24 was
                invented (§3-S2 요약 패널 퍼널). */}
            {q.data ? (
              <p className={s.rankSub}>
                {q.data.inScope === q.data.totalGrids
                  ? `서울 전역 ${int(q.data.totalGrids)}개 격자를 등급순으로 추렸습니다`
                  : `서울 ${int(q.data.totalGrids)}개 격자 중 범위 안 ${int(q.data.inScope)}개를 등급순으로 추렸습니다`}
              </p>
            ) : null}
          </header>

          {q.isPending ? <Loading /> : null}
          {q.isError ? <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} /> : null}
          {q.data && q.data.items.length === 0 ? <Empty /> : null}
          {q.data && q.data.items.length > 0 ? (
            <ul className={s.list}>
              {q.data.items.map((cell, i) => (
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

        <aside className={s.mapPanel}>
          <header className={s.mapHead}>
            <h2 className={s.mapTitle}>입지 등급</h2>
            <p className={ui.caption}>격자 하나가 100m 사각형입니다</p>
          </header>
          <GridMap
            uptae={uptae}
            focus={focus}
            candidateIds={candidateIds}
            selectedId={selectedId}
            hoveredId={hoveredId}
            onSelect={(cell) => setSelectedId(cell.gridId)}
          />
        </aside>
      </main>

      <CaveatStrip />
    </>
  );
}
