import { useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { api } from "../api/client";
import type { GridDetail, Meta } from "../api/types";
import EconomicsCard from "../components/EconomicsCard";
import { ErrorState, Loading } from "../components/states";
import { SOURCES } from "../copy";
import { stationAnchor } from "../components/CandidateCard";
import { int, meters, pct0, pct1, signedCount } from "../lib/format";
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

  const rank = rec.data ? rec.data.items.findIndex((c) => c.gridId === gridId) + 1 : 0;

  return (
    <div className={s.page}>
      {/* ── breadcrumb bar ─────────────────────────────────────────── */}
      <div className={s.crumb}>
        <button className={s.back} onClick={() => go(from === "results" ? { name: "results" } : { name: "landing" })}>
          ← {from === "results" ? "결과 목록으로" : "처음으로"}
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
      ) : detail.isError ? (
        <div className={s.pad}>
          <ErrorState onRetry={() => detail.refetch()} detail={String(detail.error)} />
        </div>
      ) : (
        <Body d={detail.data} meta={meta.data} uptae={uptae} search={search} />
      )}
    </div>
  );
}

function Body({
  d,
  meta,
  uptae,
  search,
}: {
  d: GridDetail;
  meta: Meta | undefined;
  uptae: string;
  search: ReturnType<typeof useSearch>;
}) {
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
              {uptae} {d.grade}등급 · 상위 {d.grade * 10}%
            </span>
            {d.confidence === "partial" ? (
              <span className={s.pillGrayDark}>상권 밖 · 부분 데이터</span>
            ) : null}
          </div>
          <h1 className={s.heroTitle}>{d.admDong ?? "행정동 미상"}</h1>
          <p className={s.heroSub}>
            서울 {d.district ?? "자치구 미상"} {d.admDong ?? ""}
            {d.nearestStation ? ` · ${stationAnchor(d.nearestStation)}` : ""}
            {" · 100m 격자"}
          </p>
        </div>
        <div className={s.heroGrade}>
          <span className={s.heroGradeLabel}>입지 등급</span>
          <strong className={s.heroGradeNum}>{d.grade}등급</strong>
          <span className={s.heroGradeCap}>이 등급 자리 실측 3년 생존율 {pct1(d.observedSurvival)}</span>
        </div>
      </header>

      <main className={s.body}>
        <div className={s.main}>
          {/* ── KPI row ──────────────────────────────────────────── */}
          <div className={s.kpis}>
            <div className={s.kpi}>
              <span className={s.kpiLabel}>실측 3년 생존율</span>
              <p className={s.kpiV}>
                <strong className={s.kpiGreen}>{pct0(d.observedSurvival)}</strong>
              </p>
              <span className={s.kpiCap}>
                같은 등급 자리 실측{overall !== null ? ` · 서울 전체 ${pct0(overall)}` : ""}
              </span>
            </div>
            <div className={s.kpi}>
              <span className={s.kpiLabel}>같은 업종 영업 점포</span>
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
                {d.competition.openings36m !== null
                  ? `최근 3년 개업 ${signedCount(d.competition.openings36m)}`
                  : d.competition.openingsTotal !== null
                    ? `누적 개업 ${int(d.competition.openingsTotal)} · 폐업 ${
                        d.competition.closuresTotal !== null ? int(d.competition.closuresTotal) : "정보 없음"
                      }`
                    : "개업 이력 정보 없음"}
              </span>
            </div>
            <div className={s.kpi}>
              <span className={s.kpiLabel}>역 접근성</span>
              <p className={s.kpiV}>
                {d.nearestStation?.distanceM != null ? (
                  <strong>{meters(d.nearestStation.distanceM)}</strong>
                ) : (
                  <strong className={s.kpiMuted}>정보 없음</strong>
                )}
              </p>
              <span className={s.kpiCap}>
                {d.nearestStation
                  ? `${d.nearestStation.name} 기준${
                      d.nearestStation.stations500m !== null
                        ? ` · 반경 500m 역 ${int(d.nearestStation.stations500m)}곳`
                        : ""
                    }`
                  : "인근 역 정보 없음"}
              </span>
            </div>
          </div>

          {/* ── economics (centrepiece) ──────────────────────────── */}
          <EconomicsCard
            gridId={d.gridId}
            uptae={uptae}
            grade={d.grade}
            rentMonthly={search.rentMonthly}
            upfront={search.upfront}
            onBudgetChange={(patch) => search.set(patch)}
          />

          {/* ── why this grid: honest comparisons ────────────────── */}
          <section className={s.card}>
            <div className={s.cardHead}>
              <h2>왜 이 자리인가 · 실측 신호</h2>
              <p>이 격자의 실측값을 이웃·서울 전체와 비교한 것입니다. 상관관계이며 인과가 아닙니다.</p>
            </div>
            <div className={s.bars}>
              <BarPair
                label="이웃 자리 3년 생존율"
                a={{ name: "이 격자 이웃", value: d.areaSurvival.rate, render: pct1 }}
                b={{ name: "서울 전체", value: overall, render: pct1 }}
                note={
                  d.areaSurvival.sample !== null
                    ? `표본 ${int(d.areaSurvival.sample)}${d.resolutions.areaSurvival ? ` · ${d.resolutions.areaSurvival}` : ""}`
                    : undefined
                }
              />
              <BarPair
                label="같은 업종 영업 점포"
                a={{ name: "이 격자", value: d.competition.shopsHere, render: (v) => `${int(v)}곳` }}
                b={{ name: "이웃 평균", value: d.competition.shopsNeighbor, render: (v) => `${int(v)}곳` }}
              />
              <BarPair
                label="누적 개업 vs 폐업"
                a={{ name: "개업", value: d.competition.openingsTotal, render: int }}
                b={{ name: "폐업", value: d.competition.closuresTotal, render: int }}
              />
            </div>
          </section>

          {/* ── AI report (real LLM call, whitelist-guarded server-side) ── */}
          <section className={s.card}>
            <div className={s.cardHeadRow}>
              <div className={s.cardHead}>
                <h2>AI 근거 리포트</h2>
                <p>실측치 구조체를 인용해 생성된 설명입니다. 숫자는 데이터가, 문장은 LLM이 담당합니다.</p>
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
                <h2>이미 많은 곳 vs 최근 급증한 곳</h2>
                <p>오래 버틴 점포가 많은 곳은 검증된 자리, 단기 급증은 과열 신호입니다.</p>
              </div>
              <div className={s.vs}>
                <div className={s.vsGreen}>
                  <span>영업 점포</span>
                  <strong>
                    {d.competition.shopsHere !== null ? `${int(d.competition.shopsHere)}곳` : "정보 없음"}
                  </strong>
                  <em>많을수록 검증된 자리 신호</em>
                </div>
                <div className={s.vsOrange}>
                  <span>{d.competition.openings36m !== null ? "최근 3년 개업" : "누적 개업"}</span>
                  <strong>
                    {d.competition.openings36m !== null
                      ? signedCount(d.competition.openings36m)
                      : d.competition.openingsTotal !== null
                        ? int(d.competition.openingsTotal)
                        : "정보 없음"}
                  </strong>
                  <em>단기 급증은 과열 신호</em>
                </div>
              </div>
              <div className={s.verdict}>
                {d.signal === "verified"
                  ? "검증된 자리 — 영업 점포가 많고 최근 급증하지 않았습니다"
                  : d.signal === "overheated"
                    ? "과열 신호 — 최근 개업이 급증했습니다. 진입 시점 주의"
                    : "판정 신호 산출 대기 — 36개월 개업 추이 지표가 실리면 표시됩니다"}
              </div>
            </section>

            <section className={s.card}>
              <div className={s.cardHead}>
                <h2>위험 요인과 신뢰도</h2>
                <p>모델이 확신하지 못하는 부분을 함께 표기합니다</p>
              </div>
              <div className={s.risks}>
                {search.rentMonthly === null ? (
                  <RiskRow level="high" title="임대료 미입력" desc="손익 계산에 임대료가 반영되지 않았습니다. 위 경제성 카드에 입력하세요." />
                ) : (
                  <RiskRow level="low" title="임대료 입력됨" desc={`월 ${int(search.rentMonthly)}만 원 기준으로 손익이 계산됩니다.`} />
                )}
                {d.confidence === "partial" ? (
                  <RiskRow
                    level="mid"
                    title="상권 밖 격자"
                    desc={`매출·유동 정보가 없어 일부 축이 비어 있습니다${d.missingAxes.length > 0 ? `: ${d.missingAxes.join(", ")}` : "."}`}
                  />
                ) : (
                  <RiskRow level="low" title="상권 안 격자" desc="매출·유동 축 데이터가 존재합니다." />
                )}
                <RiskRow level="mid" title="행정동 단위 값" desc="수요·인구 지표는 행정동 단위라 옆 격자와 같은 값입니다." />
                <RiskRow level="mid" title="모델 한계" desc="AUC 0.59, 무작위보다 나은 수준입니다. 등급은 입지의 확률이지 성패의 보증이 아닙니다." />
              </div>
            </section>
          </div>

          {/* ── observed by grade (figma 매물 slot → real table) ──── */}
          <section className={s.card}>
            <div className={s.cardHead}>
              <h2>등급별 실측 3년 생존율</h2>
              <p>같은 조건에서 자리 등급만 다를 때, 과거 자리들이 실제로 남긴 기록입니다.</p>
            </div>
            {meta ? (
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>등급</th>
                    <th>실측 3년 생존율</th>
                    <th>관측 표본</th>
                    <th>신뢰구간</th>
                  </tr>
                </thead>
                <tbody>
                  {meta.observedByGrade.map((g) => (
                    <tr key={g.grade} className={g.grade === d.grade ? s.rowOn : undefined}>
                      <td>
                        {g.grade}등급 (상위 {g.grade * 10}%)
                        {g.grade === d.grade ? <span className={s.rowTag}>이 자리</span> : null}
                      </td>
                      <td>{pct1(g.survival)}</td>
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
        </div>

        {/* ── sidebar ──────────────────────────────────────────────── */}
        <aside className={s.side}>
          <div className={s.loan}>
            <span className={s.loanTag}>KB 창업자금 대출 · 연계 기획</span>
            <h3>이 자리의 분석 결과로 대출 상담을 이어갈 수 있습니다</h3>
            <ul className={s.loanList}>
              <li>함께 전달되는 것 · 입지 등급</li>
              <li>등급별 실측 3년 생존율</li>
              <li>입력한 조건의 손익 계산 결과</li>
            </ul>
            <button className={s.loanBtn} disabled title="연계 기획 — 데모에서는 동작하지 않습니다">
              상담 연결 (기획)
            </button>
            <span className={s.loanCap}>한도·금리 시뮬레이션은 제공하지 않습니다. 산식이 없는 수치는 그리지 않습니다.</span>
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
            <button className={s.coachBtn} disabled title="연계 기획 — 데모에서는 동작하지 않습니다">
              1:1 상담 예약 (기획)
            </button>
          </div>

          <div className={s.alarm}>
            <strong>이 격자 변동 알림 · 연계 기획</strong>
            <p>등급은 정적 사전계산이라 지금은 변동을 감지하지 않습니다. 재계산 라운드가 돌면 알림으로 이어질 기획입니다.</p>
            <button disabled title="연계 기획 — 데모에서는 동작하지 않습니다">알림 켜기 (기획)</button>
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
    </>
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

function RiskRow({ level, title, desc }: { level: "high" | "mid" | "low"; title: string; desc: string }) {
  const cls = level === "high" ? s.lvHigh : level === "mid" ? s.lvMid : s.lvLow;
  const label = level === "high" ? "높음" : level === "mid" ? "중간" : "낮음";
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
