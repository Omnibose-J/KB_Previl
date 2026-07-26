import { useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { api } from "../api/client";
import type { GridDetail, Meta } from "../api/types";
import EconomicsCard from "../components/EconomicsCard";
import GradeBadge from "../components/GradeBadge";
import Nav from "../components/Nav";
import { ErrorState, Loading } from "../components/states";
import { ConfidenceBadge, Missing } from "../components/values";
import { SOURCES } from "../copy";
import { stationAnchor } from "../components/CandidateCard";
import { int, pct1, signedCount, survivalSentence } from "../lib/format";
import { useSearch } from "../state/search";
import s from "./S4Detail.module.css";
import ui from "../styles/ui.module.css";

// S4 상세 리포트 — spec: ui-spec.md §3-S4 (P0: 등급 + 경제성 카드 + 한계 카드).
// Shared by both entry modes; `from` only changes the breadcrumb.
// Held back to P1/P2 and deliberately absent rather than faked: SHAP 기여 바,
// /report LLM 근거, 잠식vs집적 카드, 면적 참고 카드, 대출·알림 콘셉트 카드.
// The mockup's 예시 매물 3건 and KB 대출 시뮬레이션 are deleted outright — we
// have neither listings nor a lending formula, so any number there is invented.
export default function S4Detail({
  go,
  gridId,
  from,
}: {
  go: (s: Screen) => void;
  gridId: string;
  from: "results" | "diagnosis";
}) {
  const search = useSearch();
  const uptae = search.uptae;

  const detail = useQuery({
    queryKey: ["grid", gridId, uptae],
    queryFn: () => api.gridDetail(gridId, uptae!),
    enabled: uptae !== null,
  });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });

  return (
    <>
      <Nav
        onHome={() => go({ name: "landing" })}
        right={
          from === "results" ? (
            <button className={ui.btn} onClick={() => go({ name: "results" })}>
              ← 결과 목록으로
            </button>
          ) : (
            <span className={s.crumb}>진단 결과</span>
          )
        }
      />

      <main className={s.body}>
        {detail.isPending || meta.isPending ? <Loading /> : null}
        {detail.isError ? (
          <ErrorState onRetry={() => detail.refetch()} detail={String(detail.error)} />
        ) : null}
        {detail.data && meta.data ? (
          <Report cell={detail.data} meta={meta.data} search={search} uptae={uptae!} />
        ) : null}
      </main>
    </>
  );
}

function Report({
  cell,
  meta,
  search,
  uptae,
}: {
  cell: GridDetail;
  meta: Meta;
  search: ReturnType<typeof useSearch>;
  uptae: string;
}) {
  return (
    <>
      <div className={s.main}>
        {/* Hero — the grade at display size, never "92점 · 상위 0.4%" (§3-S4). */}
        <header className={s.hero}>
          <p className={s.place}>
            {[cell.district, cell.admDong].filter(Boolean).join(" ") || "위치 정보 없음"}
            {cell.nearestStation ? ` · ${stationAnchor(cell.nearestStation)}` : ""}
          </p>
          <div className={s.heroGrade}>
            <GradeBadge grade={cell.grade} size="lg" />
            <ConfidenceBadge confidence={cell.confidence} missingAxes={cell.missingAxes} />
          </div>
          <h1 className={s.heroSentence}>{survivalSentence(cell.observedSurvival)}</h1>
          <p className={s.heroSub}>
            이 등급 자리들의 실측 3년 생존율 {pct1(cell.observedSurvival)}
            {meta.overallSurvival !== null ? ` · 서울 전체 ${pct1(meta.overallSurvival)}` : ""}
          </p>
        </header>

        {/* KPI 3장 — 확률 % 단독 노출은 금지, 등급과 실측치로만 말한다. */}
        <div className={s.kpis}>
          <Kpi title="경쟁 · 이 자리">
            <Line label="영업 중인 점포" value={cell.competition.shopsHere} render={int} />
            <Line label="이웃 300m 점포" value={cell.competition.shopsNeighbor} render={int} />
          </Kpi>
          <Kpi title="이력">
            <Line
              label="최근 3년 개업"
              value={cell.competition.openings36m}
              render={signedCount}
            />
            <Line label="누적 개업" value={cell.competition.openingsTotal} render={int} />
            <Line label="누적 폐업" value={cell.competition.closuresTotal} render={int} />
          </Kpi>
          <Kpi title="접근성">
            {cell.nearestStation ? (
              <p className={s.kpiBig}>{stationAnchor(cell.nearestStation)}</p>
            ) : (
              <Missing reason="가까운 역 없음" />
            )}
          </Kpi>
        </div>

        <EconomicsCard
          gridId={cell.gridId}
          uptae={uptae}
          grade={cell.grade}
          rentMonthly={search.rentMonthly}
          upfront={search.upfront}
          onBudgetChange={(patch) => search.set(patch)}
        />
      </div>

      <aside className={s.side}>
        <section className={ui.card}>
          <h2 className={s.sideTitle}>이 등급의 실측</h2>
          <table className={s.gradeTable}>
            <tbody>
              {meta.observedByGrade.map((g) => (
                <tr key={g.grade} className={g.grade === cell.grade ? s.rowOn : undefined}>
                  <th>{g.grade}등급</th>
                  <td>{pct1(g.survival)}</td>
                  {/* 표본수는 A1 산출 전까지 null — 빈칸으로 두지 않고 없음을 적는다 */}
                  <td className={s.sample}>{g.n === null ? "표본 미상" : `표본 ${int(g.n)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* 데이터·한계 카드 — replaces the mockup's marketing block entirely. */}
        <section className={ui.card}>
          <h2 className={s.sideTitle}>데이터와 한계</h2>
          <ul className={s.limits}>
            {meta.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
            <li>비정형 데이터(검색 트렌드·점포 언급량)는 두 방식으로 측정했고, 예측에 기여하지 않아 쓰지 않았습니다.</li>
            <li>임대료는 사용자가 넣은 값입니다 — 매물별 임대료 데이터는 공개돼 있지 않습니다.</li>
            <li>점포 면적과 층은 순위에 넣지 않았습니다. 자리가 아니라 사장님의 선택이기 때문입니다.</li>
          </ul>
          <p className={s.sourceTitle}>쓴 데이터</p>
          <p className={s.sources}>{SOURCES.join(" · ")}</p>
          <p className={ui.captionBlock}>
            {meta.asOf ? `기준 시점 ${meta.asOf}` : "기준 시점 정보 없음"}
          </p>
        </section>
      </aside>
    </>
  );
}

function Kpi({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className={s.kpi}>
      <h2 className={s.kpiTitle}>{title}</h2>
      {children}
    </section>
  );
}

function Line({
  label,
  value,
  render,
}: {
  label: string;
  value: number | null;
  render: (v: number) => string;
}) {
  return (
    <p className={s.line}>
      <span>{label}</span>
      {value === null ? <Missing /> : <strong>{render(value)}</strong>}
    </p>
  );
}
