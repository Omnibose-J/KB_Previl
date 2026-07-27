import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { ApiError, api } from "../api/client";
import type { GridDetail, Meta } from "../api/types";
import EconomicsCard from "../components/EconomicsCard";
import GoodwillCard from "../components/GoodwillCard";
import { ErrorState, Loading } from "../components/states";
import { SOURCES } from "../copy";
import { int, meters, pct0, pct1, stationAnchor, survivalSentence } from "../lib/format";
import { isRecommendable } from "../lib/grade";
import { useSearch } from "../state/search";
import s from "./S4Detail.module.css";

// S4, rebuilt against figma-snapshot S4: breadcrumb bar → dark hero (pills +
// big grade) → KPI 3 → economics (the one card figma lacks and we keep — it is
// the demo's centrepiece) → signal bars → AI report (real POST /report) →
// 경쟁/위험 pair → observed-by-grade table, with the 4-card sidebar.
//
// Figma blocks that had no data behind them are kept as VISUALS but with
// honest content: 대출/코칭/알림 cards carry a "연계 기획" label and no
// simulated numbers; the 매물 table slot became the observed-survival table.

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
  const rec = useQuery({
    queryKey: ["recommend", uptae, search.districts],
    queryFn: () => api.recommend(uptae!, search.districts),
    enabled: uptae !== null && from === "results",
  });

  if (!uptae) {
    return (
      <main className={s.guard}>
        <p>업종 정보가 없습니다.</p>
        <button onClick={() => go({ name: "input" })}>조건 입력으로</button>
      </main>
    );
  }

  // Rank within the same threshold-cut list S3 renders (lib/grade.ts).
  const rank = rec.data
    ? rec.data.items.filter(isRecommendable).findIndex((c) => c.gridId === gridId) + 1
    : 0;

  return (
    <div className={s.page}>
      {/* ── breadcrumb bar ─────────────────────────────────────────── */}
      <div className={s.crumb}>
        {/* diagnosis entries come from the S3 map — back returns there too */}
        <button className={s.back} onClick={() => go({ name: "results" })}>
          ← {from === "results" ? "결과 목록으로" : "지도로 돌아가기"}
        </button>
        <span className={s.crumbPath}>
          {from === "results" ? (rank > 0 ? `추천 ${rank}위` : "추천 후보") : "진단 결과"}
          {detail.data?.admDong ? `  /  ${detail.data.admDong}` : ""}
        </span>
        <span className={s.crumbSpacer} />
      </div>

      {detail.isPending ? (
        <div className={s.pad}>
          <Loading label="격자 정보를 불러오는 중…" />
        </div>
      ) : detail.error instanceof ApiError && detail.error.status === 404 ? (
        /* "평가 불가" is an ANSWER, not a failure (serving-design §5-7/§7):
           no retry button, no error styling. */
        <div className={s.pad}>
          <div className={s.unrated} role="status">
            <strong>이 자리는 평가하지 않았어요</strong>
            <p>{detail.error.detail || "주변에 가게가 문을 연 기록이 너무 적어서 등급을 매길 수 없어요."}</p>
            <p className={s.unratedNote}>나쁜 자리라는 뜻이 아니라, 판단할 기록이 없다는 뜻이에요.</p>
          </div>
        </div>
      ) : detail.isError ? (
        <div className={s.pad}>
          <ErrorState onRetry={() => detail.refetch()} detail={String(detail.error)} />
        </div>
      ) : (
        <Body d={detail.data} meta={meta.data} uptae={uptae} />
      )}
    </div>
  );
}

// One question per view (ui-spec §0 원칙 1): the report is split into three
// tabs — 평가(what is this spot) / 손익·권리금(what does it cost me) /
// 실측 데이터(the evidence tables). Panels stay MOUNTED (hidden attr) so tab
// switches never wipe user inputs or refetch queries.
type Tab = "evalTab" | "moneyTab" | "dataTab";

function Body({ d, meta, uptae }: { d: GridDetail; meta: Meta | undefined; uptae: string }) {
  const search = useSearch();
  const [tab, setTab] = useState<Tab>("evalTab");
  // Goodwill lives in its own dialog (owner call 2026-07-27): the money tab
  // keeps only an entry card. The dialog stays MOUNTED while closed so typed
  // inputs (호가·잔여·자산 rows) survive close/reopen and tab switches.
  const [gwOpen, setGwOpen] = useState(false);
  useEffect(() => {
    if (!gwOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setGwOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [gwOpen]);
  const report = useQuery({
    queryKey: ["report", d.gridId, uptae],
    queryFn: () => api.report(d.gridId, uptae),
    staleTime: Infinity,
    retry: 0,
  });

  const overall = meta?.overallSurvival ?? null;

  return (
    <>
      {/* ── dark hero ──────────────────────────────────────────────── */}
      <header className={s.hero}>
        <div className={s.heroL}>
          <div className={s.heroPills}>
            {d.signal === "verified" ? <span className={s.pillGreenDark}>검증된 자리</span> : null}
            {d.signal === "overheated" ? <span className={s.pillOrangeDark}>과열 신호</span> : null}
            <span className={s.pillYellowDark}>
              {uptae} {d.grade}등급
            </span>
            {d.confidence === "partial" ? (
              <span className={s.pillGrayDark}>상권 밖 · 부분 데이터</span>
            ) : null}
          </div>
          <h1 className={s.heroTitle}>{d.admDong ?? "행정동 미상"}</h1>
          <p className={s.heroSub}>
            서울 {d.district ?? "자치구 미상"} {d.admDong ?? ""}
            {d.nearestStation ? ` · ${stationAnchor(d.nearestStation)}` : ""}
          </p>
        </div>
        <div className={s.heroGrade}>
          <span className={s.heroGradeLabel}>입지 등급</span>
          <strong className={s.heroGradeNum}>{d.grade}등급</strong>
          <span className={s.heroGradeCap}>이런 자리 {survivalSentence(d.observedSurvival)}</span>
        </div>
      </header>

      <main className={s.body}>
        <div className={s.main}>
          <nav className={s.tabBar} aria-label="리포트 구역">
            <button className={tab === "evalTab" ? s.tabOn : s.tab} onClick={() => setTab("evalTab")}>
              자리 평가
            </button>
            <button className={tab === "moneyTab" ? s.tabOn : s.tab} onClick={() => setTab("moneyTab")}>
              손익·권리금
            </button>
            <button className={tab === "dataTab" ? s.tabOn : s.tab} onClick={() => setTab("dataTab")}>
              기록 자세히
            </button>
          </nav>

          <div className={s.panel} hidden={tab !== "evalTab"}>
          {/* ── KPI row ──────────────────────────────────────────── */}
          <div className={s.kpis}>
            <div className={s.kpi}>
              {/* Class stat, not a spot stat — the dynamic label says so, else
                  the same 75% on every top-graded detail reads as hardcoded. */}
              <span className={s.kpiLabel}>{d.grade}등급 자리의 실제 3년 생존율</span>
              <p className={s.kpiV}>
                <strong className={s.kpiGreen}>{pct0(d.observedSurvival)}</strong>
              </p>
              <span className={s.kpiCap}>
                같은 등급이면 값이 같아요{overall !== null ? ` · 서울 전체는 ${pct0(overall)}` : ""}
              </span>
            </div>
            <div className={s.kpi}>
              <span className={s.kpiLabel}>주변의 같은 업종 가게</span>
              <p className={s.kpiV}>
                {d.competition.shopsHere !== null ? (
                  <>
                    <strong>{int(d.competition.shopsHere)}</strong>
                    <em>곳</em>
                  </>
                ) : (
                  <strong className={s.kpiMuted}>정보 없음</strong>
                )}
              </p>
              <span className={s.kpiCap}>
                {d.competition.openingsTotal !== null
                  ? `지금까지 ${int(d.competition.openingsTotal)}곳 열고 ${
                      d.competition.closuresTotal !== null
                        ? `${int(d.competition.closuresTotal)}곳 닫았어요`
                        : "폐업 수는 정보 없음"
                    }`
                  : "개업 기록 없음"}
              </span>
            </div>
            <div className={s.kpi}>
              <span className={s.kpiLabel}>가까운 역</span>
              <p className={s.kpiV}>
                {d.nearestStation?.distanceM != null ? (
                  <strong>{meters(d.nearestStation.distanceM)}</strong>
                ) : (
                  <strong className={s.kpiMuted}>정보 없음</strong>
                )}
              </p>
              <span className={s.kpiCap}>
                {d.nearestStation
                  ? `${d.nearestStation.name}${
                      d.nearestStation.stations500m !== null
                        ? ` · 걸어갈 만한 역 ${int(d.nearestStation.stations500m)}곳`
                        : ""
                    }`
                  : "가까운 역 없음"}
              </span>
            </div>
          </div>

          {/* ── why this grid: honest comparisons ────────────────── */}
          <section className={s.card}>
            <div className={s.cardHead}>
              <h2>이 자리의 기록</h2>
              <p>주변과 서울 전체에 비해 어떤지 봤어요.</p>
            </div>
            <div className={s.bars}>
              <BarPair
                label="주변 가게 3년 생존율"
                a={{ name: "이 자리 주변", value: d.areaSurvival.rate, render: pct1 }}
                b={{ name: "서울 전체", value: overall, render: pct1 }}
                note={
                  d.areaSurvival.sample !== null
                    ? `표본 ${int(d.areaSurvival.sample)}${d.resolutions.areaSurvival ? ` · ${d.resolutions.areaSurvival}` : ""}`
                    : undefined
                }
              />
              <BarPair
                label="같은 업종 가게 수"
                a={{ name: "이 자리", value: d.competition.shopsHere, render: (v) => `${int(v)}곳` }}
                b={{ name: "주변 평균", value: d.competition.shopsNeighbor, render: (v) => `${int(v)}곳` }}
              />
              <BarPair
                label="연 가게 vs 닫은 가게"
                a={{ name: "열었다", value: d.competition.openingsTotal, render: (v) => `${int(v)}곳` }}
                b={{ name: "닫았다", value: d.competition.closuresTotal, render: (v) => `${int(v)}곳` }}
              />
            </div>
          </section>

          {/* ── AI report (real LLM call, whitelist-guarded server-side) ── */}
          <section className={s.card}>
            <div className={s.cardHeadRow}>
              <div className={s.cardHead}>
                <h2>AI가 정리한 이 자리</h2>
              </div>
              <span className={s.llmTag}>LLM 생성 · 근거 데이터 인용</span>
            </div>
            {report.isPending ? (
              <Loading label="근거 문장 생성 중…" />
            ) : report.isError ? (
              <ErrorState onRetry={() => report.refetch()} detail={String(report.error)} />
            ) : (
              <div className={s.reportBody}>
                {report.data.sentences.map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
            )}
          </section>

          {/* ── 경쟁 + 위험 pair ─────────────────────────────────── */}
          <div className={s.pair}>
            <section className={s.card}>
              <div className={s.cardHead}>
                <h2>경쟁이 걱정되세요?</h2>
                <p>같은 업종 가게가 오래 버티고 있는 곳은 그만큼 검증된 자리예요.</p>
              </div>
              <div className={s.vs}>
                <div className={s.vsGreen}>
                  <span>영업 중인 가게</span>
                  <strong>
                    {d.competition.shopsHere !== null ? `${int(d.competition.shopsHere)}곳` : "정보 없음"}
                  </strong>
                  <em>오래 버틴 가게가 많다는 뜻이에요</em>
                </div>
                <div className={s.vsOrange}>
                  <span>지금까지 연 가게</span>
                  <strong>
                    {d.competition.openingsTotal !== null ? `${int(d.competition.openingsTotal)}곳` : "정보 없음"}
                  </strong>
                  <em>갑자기 늘면 과열 신호예요</em>
                </div>
              </div>
              {/* verified/overheated verdict strip returns when lane A ships
                  the signal column — until then there is nothing to say. */}
              {d.signal === "verified" ? (
                <div className={s.verdict}>검증된 자리 — 영업 점포가 많고 최근 급증하지 않았습니다</div>
              ) : d.signal === "overheated" ? (
                <div className={s.verdict}>과열 신호 — 최근 개업이 급증했습니다. 진입 시점 주의</div>
              ) : null}
            </section>

            <section className={s.card}>
              <div className={s.cardHead}>
                <h2>미리 알아두세요</h2>
              </div>
              {/* Only actual risks earn a row. Model-limit copy lives in the
                  data card below, sourced from meta().caveats — restating it
                  here with a hardcoded AUC was a second source of truth. */}
              <div className={s.risks}>
                {search.rentMonthly === null ? (
                  <RiskRow level="high" title="임대료를 아직 안 넣으셨어요" desc="임대료를 넣으면 손익까지 계산해 드려요. 손익·권리금 탭에서 넣을 수 있어요." />
                ) : null}
                {d.confidence === "partial" ? (
                  <RiskRow
                    level="mid"
                    title="주변 매출 기록이 없는 자리예요"
                    desc="매출·유동 관련 숫자는 비어 있어요. 없는 값을 채워 넣지 않았어요."
                  />
                ) : null}
                <RiskRow level="mid" title="인구 숫자는 동 단위예요" desc="바로 옆 자리와 같은 값일 수 있어요." />
              </div>
            </section>
          </div>
          </div>

          <div className={s.panel} hidden={tab !== "moneyTab"}>
          {/* ── economics (centrepiece) ──────────────────────────── */}
          <EconomicsCard
            gridId={d.gridId}
            uptae={uptae}
            grade={d.grade}
            rentMonthly={search.rentMonthly}
            upfront={search.upfront}
            onBudgetChange={(patch) => search.set(patch)}
          />

          {/* ── 권리금 진입 카드 — 리포트 본체는 다이얼로그로 ────── */}
          <section className={s.card}>
            <div className={s.cardHead}>
              <h2>부르는 권리금, 적당한가요?</h2>
              <p>이 자리 기록으로 참고가를 계산해 드려요. 감정평가는 아니에요.</p>
            </div>
            {d.sales.available ? (
              <button className={s.gwOpenBtn} onClick={() => setGwOpen(true)}>
                권리금 계산해 보기
              </button>
            ) : (
              <p className={s.gwNone}>
                이 자리는 주변 매출 기록이 없어서 권리금 참고가를 계산할 수 없어요.
              </p>
            )}
          </section>
          </div>

          <div className={s.panel} hidden={tab !== "dataTab"}>
          {/* ── observed by grade (figma 매물 slot → real table) ──── */}
          <section className={s.card}>
            <div className={s.cardHead}>
              <h2>등급별 실제 3년 생존율</h2>
              <p>자리 등급만 달랐을 때 실제 결과예요.</p>
            </div>
            {meta ? (
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>등급</th>
                    <th>실제 3년 생존율</th>
                    <th>관측 표본</th>
                    <th>신뢰구간</th>
                  </tr>
                </thead>
                <tbody>
                  {meta.observedByGrade.map((g) => (
                    <tr key={g.grade} className={g.grade === d.grade ? s.rowOn : undefined}>
                      <td>
                        {g.grade}등급
                        {g.grade === d.grade ? <span className={s.rowTag}>이 자리</span> : null}
                      </td>
                      <td>
                        {/* inline bar: the 75%→29% cliff should be visible,
                            not just legible (UX critique) */}
                        <span className={s.pctBar}>
                          <i style={{ width: `${Math.round(g.survival * 130)}px` }} />
                          <em>{pct1(g.survival)}</em>
                        </span>
                      </td>
                      <td>{g.n !== null ? int(g.n) : "산출 대기"}</td>
                      <td>
                        {g.ciLow !== null && g.ciHigh !== null
                          ? `${pct1(g.ciLow)} ~ ${pct1(g.ciHigh)}`
                          : "산출 대기"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Loading />
            )}
          </section>

          {/* ── survival by period (new /meta fields, 2026-07-27) ──── */}
          {meta && meta.survivalByPeriod.length > 0 ? (
            <section className={s.card}>
              <div className={s.cardHead}>
                <h2>1년, 3년, 5년 뒤에는</h2>
                <p>시간이 지날수록 얼마나 남았는지예요.</p>
              </div>
              <PeriodTable meta={meta} grade={d.grade} />
              <p className={s.tableFoot}>
                * 5년 숫자는 다른 시기({periodOf(meta, 5)?.cohort ?? "별도"})에 연 가게들 기준이라 1·3년과
                이어서 읽으면 안 돼요.
              </p>
            </section>
          ) : null}

          {/* ── grade × area (observed, not causal — §5-6) ─────────── */}
          {meta?.gradeArea ? (
            <section className={s.card}>
              <div className={s.cardHead}>
                <h2>가게 크기별 기록</h2>
                <p>넓은 가게가 더 버텼다는 기록이지, 넓히면 잘된다는 뜻은 아니에요. 추천 순위와도 무관해요.</p>
              </div>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>밴드</th>
                    {meta.gradeArea.areaBands.map((a) => (
                      <th key={a}>{a}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {meta.gradeArea.gradeBands.map((band, bi) => {
                    // Positional grade→band mapping is only valid for the
                    // 3-band shape; on any other server shape, skip the
                    // highlight rather than mark the wrong row.
                    const isHere =
                      meta.gradeArea!.gradeBands.length === 3 && bi === bandIndex(d.grade);
                    return (
                      <tr key={band} className={isHere ? s.rowOn : undefined}>
                        <td>
                          {band}
                          {isHere ? <span className={s.rowTag}>이 자리</span> : null}
                        </td>
                        {meta.gradeArea!.survival[bi].map((v, ai) => (
                          <td key={ai}>{v !== null ? pct1(v) : "정보 없음"}</td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className={s.tableFoot}>검증 기준 {meta.gradeArea.bench}</p>
            </section>
          ) : null}
          </div>
        </div>

        {/* ── sidebar ──────────────────────────────────────────────── */}
        <aside className={s.side}>
          <div className={s.loan}>
            <span className={s.loanTag}>KB 창업자금 대출 · 연계 기획</span>
            <h3>이 분석 그대로 대출 상담까지</h3>
            <ul className={s.loanList}>
              <li>함께 전달되는 것 · 입지 등급</li>
              <li>등급별 실제 3년 생존율</li>
              <li>입력한 조건의 손익 계산 결과</li>
            </ul>
            <span className={s.loanCap}>한도·금리 시뮬레이션은 제공하지 않습니다.</span>
          </div>

          <div className={s.coach}>
            <span className={s.coachTag}>전문가 최종 코칭 · 연계 기획</span>
            <p>AI가 1차 스크리닝을 마쳤습니다. KB 소상공인 컨설팅 전문가와 최종 점검을 이어가세요.</p>
            <div className={s.coachChips}>
              <span>상권 분석</span>
              <span>창업 일반</span>
              <span>금융 상담</span>
              <span>경영 상담</span>
            </div>
          </div>

          <div className={s.alarm}>
            <strong>이 격자 변동 알림 · 연계 기획</strong>
            <p>재계산 라운드가 돌면 변동 알림으로 이어질 기획입니다.</p>
          </div>

          <div className={s.datacard}>
            <strong>데이터 출처 및 한계</strong>
            <ul>
              <li>· 정형 · {SOURCES.join(", ")}</li>
              <li>· 모델 · LightGBM 분류 + 시간분리 홀드아웃 검증</li>
              <li>· 비정형 · 인스타·블로그 등은 두 방식으로 측정했으나 기여가 없어 쓰지 않습니다</li>
              {meta?.caveats.map((c) => <li key={c}>· 한계 · {c}</li>)}
            </ul>
            <span className={s.dataFoot}>최종 갱신 {meta?.asOf ?? "정보 없음"}</span>
          </div>
        </aside>
      </main>

      {/* ── 권리금 리포트 다이얼로그 — mounted while closed (inputs survive) ── */}
      <div className={s.gwOverlay} hidden={!gwOpen} onClick={() => setGwOpen(false)}>
        <div
          className={s.gwDialog}
          role="dialog"
          aria-modal="true"
          aria-label="권리금 리포트"
          onClick={(e) => e.stopPropagation()}
        >
          <button className={s.gwClose} onClick={() => setGwOpen(false)} aria-label="닫기">
            ✕
          </button>
          <GoodwillCard d={d} uptae={uptae} />
        </div>
      </div>
    </>
  );
}

/** grade → holdout band row (1 = top decile band, 10 = bottom, rest middle). */
function bandIndex(grade: number): number {
  return grade === 1 ? 0 : grade === 10 ? 2 : 1;
}

function periodOf(meta: Meta, years: 1 | 3 | 5) {
  return meta.survivalByPeriod.find((p) => p.years === years) ?? null;
}

/** 1·3y share the 2023 cohort; 5y is a separate fit and gets a starred column
 *  instead of a shared axis (serving-design §5-5). */
function PeriodTable({ meta, grade }: { meta: Meta; grade: number }) {
  const periods = ([1, 3, 5] as const).map((y) => periodOf(meta, y));
  const bandLabels = periods.find((p) => p?.bands)?.bands?.map((b) => b.band) ?? [];
  if (bandLabels.length === 0) return null;
  return (
    <table className={s.table}>
      <thead>
        <tr>
          <th>밴드</th>
          {periods.map((p, i) =>
            p?.bands ? (
              <th key={i}>
                {p.years}년{p.years === 5 ? " *" : ""}
                {p.testWindow ? <span className={s.thCap}> 검증 {p.testWindow}</span> : null}
              </th>
            ) : null,
          )}
        </tr>
      </thead>
      <tbody>
        {bandLabels.map((label, bi) => {
          const isHere = bandLabels.length === 3 && bi === bandIndex(grade);
          return (
            <tr key={label} className={isHere ? s.rowOn : undefined}>
              <td>
                {label}
                {isHere ? <span className={s.rowTag}>이 자리</span> : null}
              </td>
              {periods.map((p, i) => {
                if (!p?.bands) return null;
                // Join across cohorts by band LABEL, never by position — the
                // 5y period is a separate fit and owes us no row order.
                const b = p.bands.find((x) => x.band === label);
                return (
                  <td key={i}>
                    {b?.survival !== null && b?.survival !== undefined ? pct1(b.survival) : "정보 없음"}
                    {b?.n !== null && b?.n !== undefined ? (
                      <span className={s.tdCap}> 표본 {int(b.n)}</span>
                    ) : null}
                  </td>
                );
              })}
            </tr>
          );
        })}
        <tr className={s.overallRow}>
          <td>전체</td>
          {periods.map((p, i) =>
            p?.bands ? <td key={i}>{p.overall !== null ? pct1(p.overall) : "정보 없음"}</td> : null,
          )}
        </tr>
      </tbody>
    </table>
  );
}

/** Two real values on a shared scale — the only honest way to size a bar.
 *  Either side NULL renders the row with 정보 없음 instead of a guessed length. */
function BarPair({
  label,
  a,
  b,
  note,
}: {
  label: string;
  a: { name: string; value: number | null; render: (v: number) => string };
  b: { name: string; value: number | null; render: (v: number) => string };
  note?: string;
}) {
  const max = Math.max(a.value ?? 0, b.value ?? 0);
  return (
    <div className={s.barPair}>
      <div className={s.barLabel}>
        {label}
        {note ? <em>{note}</em> : null}
      </div>
      <div className={s.barRows}>
        <BarRow name={a.name} value={a.value} render={a.render} max={max} tone="yellow" />
        <BarRow name={b.name} value={b.value} render={b.render} max={max} tone="gray" />
      </div>
    </div>
  );
}

function BarRow({
  name,
  value,
  render,
  max,
  tone,
}: {
  name: string;
  value: number | null;
  render: (v: number) => string;
  max: number;
  tone: "yellow" | "gray";
}) {
  return (
    <div className={s.barRow}>
      <span className={s.barName}>{name}</span>
      <div className={s.barTrack}>
        {value !== null && max > 0 ? (
          <i
            className={tone === "yellow" ? s.barY : s.barG}
            style={{ width: `${Math.max(4, (value / max) * 100)}%` }}
          />
        ) : null}
      </div>
      <span className={s.barValue}>{value !== null ? render(value) : "정보 없음"}</span>
    </div>
  );
}

function RiskRow({ level, title, desc }: { level: "high" | "mid"; title: string; desc: string }) {
  const cls = level === "high" ? s.lvHigh : s.lvMid;
  const label = level === "high" ? "높음" : "중간";
  return (
    <div className={s.risk}>
      <span className={cls}>{label}</span>
      <div className={s.riskBody}>
        <strong>{title}</strong>
        <p>{desc}</p>
      </div>
    </div>
  );
}
