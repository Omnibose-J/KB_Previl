import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { ApiError, api } from "../api/client";
import type { GridDetail, Meta } from "../api/types";
import AiSummaryCard from "../components/AiSummaryCard";
import ChangeHistoryChart from "../components/ChangeHistoryChart";
import ConceptMixCard from "../components/ConceptMixCard";
import SalesMixCard from "../components/SalesMixCard";
import VisitorPartyCard from "../components/VisitorPartyCard";
import EconomicsCard from "../components/EconomicsCard";
import GoodwillCard from "../components/GoodwillCard";
import OccupancyCostCard from "../components/OccupancyCostCard";
import KbLinkCard from "../components/KbLinkCard";
import { ErrorState, Loading } from "../components/states";
import { int, meters, pct0, pct1, stationAnchor, survivalSentence } from "../lib/format";
import { isRecommendable } from "../lib/grade";
import { useReveal } from "../lib/reveal";
import { useSearch } from "../state/search";
import s from "./S4Detail.module.css";

// 자리 하나의 전체 리포트. 머리말 바 → 어두운 히어로 → KPI 3 → 손익 → 경쟁·위험
// → 등급별 실측표, 오른쪽에 사이드바.
//
// 데이터가 없는 시안 블록은 지우지 않고 정직한 내용으로 채웠다. 대출·코칭 카드는
// 모의 숫자를 넣지 않고 KB 실제 창구로 넘기며, 매물 표 자리는 실측 생존표가 됐다.

// 사이드바 두 카드가 나가는 곳. 코칭 카드의 칩 네 개(상권 분석·창업 일반·금융
// 상담·경영 상담)는 컨설팅 페이지가 실제로 안내하는 서비스 이름이라, 넷을 따로
// 걸지 않고 카드 하나로 같은 곳에 보낸다.
const KB_LOAN_URL = "https://obank.kbstar.com/quics?page=C103425";
const KB_CONSULTING_URL = "https://obiz.kbstar.com/quics?page=C044463";

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
  // 절은 detail 이 온 뒤에 붙으므로 그때 다시 관찰을 건다.
  useReveal([detail.data]);
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
      {/* 되돌아가기 + 현재 위치. S5 와 같은 구성이다 — 잎 화면에는 로고를 두지
          않는다. 바로 옆에 되돌아가기가 있어 이동 수단이 둘이 되고, 로고는 여기서
          제목 자리를 왼쪽으로 밀기만 했다. */}
      <div className={s.crumb}>
        {/* diagnosis entries come from the S3 map — back returns there too */}
        <button className={s.back} onClick={() => go({ name: "results" })}>
          ← {from === "results" ? "결과 목록으로" : "지도로 돌아가기"}
        </button>
        <span className={s.crumbPath}>
          {from === "results" ? (rank > 0 ? `추천 ${rank}위` : "추천 후보") : "진단 결과"}
          {detail.data?.admDong ? `  /  ${detail.data.admDong}` : ""}
        </span>
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
  // 계약기간 선택 — 등급은 그대로 두고, 기간별 «실측» 표에서 그 기간 열과
  // 리드 문장만 바꾼다. 재계산·재등급이 아니라 강조 전환이다.
  const [leaseYears, setLeaseYears] = useState<1 | 2 | 3>(3);
  // 점유비용 카드가 계산해 올려 주는 값. 그 전까지는 null 이라 아래 KB 연계
  // 카드가 아예 뜨지 않는다 — 값 없이 띄우면 «권할지 말지»를 근거 없이 고르게 된다.
  const [succession, setSuccession] = useState<number | null>(null);
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
  const overall = meta?.overallSurvival ?? null;
  // 지도 말풍선과 같은 캐시 키다 — 지도에서 눌러 들어오면 이미 받아둔 값이라
  // 행정동에서 번지로 바뀌는 깜빡임이 없다.
  const addr = useQuery({
    queryKey: ["gridAddress", d.gridId],
    queryFn: () => api.gridAddress(d.gridId),
    staleTime: Infinity,
  });

  return (
    <>
      {/* ── dark hero ──────────────────────────────────────────────── */}
      <header className={s.hero}>
        <div className={s.heroL}>
          <div className={s.heroPills}>
            <span className={s.pillYellowDark}>
              {uptae} {d.grade}등급
            </span>
            {d.confidence === "partial" ? (
              <span className={s.pillGrayDark}>상권 밖 · 부분 데이터</span>
            ) : null}
          </div>
          <h1 className={s.heroTitle}>{d.admDong ?? "행정동 미상"}</h1>
          {/* 제목이 이미 행정동이라 여기서 되풀이하지 않고 번지까지 내려간다.
              주소가 오기 전이나 인허가 기록이 없는 칸은 아는 만큼(행정동)만
              말한다 — 번지를 지어내지 않는다. */}
          <p className={s.heroSub}>
            서울 {addr.data?.label ?? `${d.district ?? "자치구 미상"} ${d.admDong ?? ""}`}
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
              <span className={s.kpiLabel}>이 자리의 {uptae} 가게</span>
              <p className={s.kpiV}>
                {d.competition.sameUptaeHere !== null ? (
                  <>
                    <strong>{int(d.competition.sameUptaeHere)}</strong>
                    <em>곳</em>
                  </>
                ) : (
                  <strong className={s.kpiMuted}>정보 없음</strong>
                )}
              </p>
              {/* 아래 각주는 업태를 가리지 않은 «음식점 전체»라 이름을 달리
                  부른다. 같은 칸 안에서 위는 업종별, 아래는 전체다. */}
              <span className={s.kpiCap}>
                {d.competition.shopsHere !== null
                  ? `영업 중인 음식점 전체는 ${int(d.competition.shopsHere)}곳`
                  : "음식점 수는 정보 없음"}
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
          <section className={s.card} data-reveal>
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
              {/* 여기는 «업태별» 수다. 업태 무관 전체 음식점 수는 아래
                  «경쟁이 걱정되세요?» 칸이 따로 보여준다. 두 값을 같은
                  이름으로 부르면 한식을 골라도 중국식을 골라도 같은 숫자가
                  나오던 예전 화면으로 되돌아간다. */}
              <BarPair
                label={`${uptae} 가게 수`}
                a={{
                  name: "이 자리 100m",
                  value: d.competition.sameUptaeHere,
                  render: (v) => `${int(v)}곳`,
                }}
                b={{
                  name: "주변 300m",
                  value: d.competition.sameUptaeNeighbor,
                  render: (v) => `${int(v)}곳`,
                }}
              />
              <BarPair
                label="연 가게 vs 닫은 가게"
                a={{ name: "열었다", value: d.competition.openingsTotal, render: (v) => `${int(v)}곳` }}
                b={{ name: "닫았다", value: d.competition.closuresTotal, render: (v) => `${int(v)}곳` }}
              />
            </div>
          </section>

          <ConceptMixCard mix={d.conceptMix} />

          {/* 가게 수 바로 뒤에 결제 구성을 둔다. 붙여 놓아야 «가게가 많은 업종
              = 돈이 도는 업종» 이 아니라는 것이 읽힌다 — 상권 1,185곳에서
              커피는 가게 27.8% / 결제 24.7%, 한식은 31.8% / 55.1% 였다. */}
          <SalesMixCard mix={d.salesMix} />

          {/* «주변에 어떤 가게가 있나» 바로 뒤 — 둘 다 관측 집계라 나란히 둔다.
              등급·생존율 블록에서 떼어 놓아야 예측처럼 읽히지 않는다. */}
          <VisitorPartyCard party={d.visitorParty} />

          {/* ── 경쟁 + 위험 pair ─────────────────────────────────── */}
          <div className={s.pair}>
            <section className={s.card} data-reveal>
              <div className={s.cardHead}>
                <h2>경쟁이 걱정되세요?</h2>
                <p>가게가 오래 버티고 있는 곳은 그만큼 검증된 자리예요.</p>
              </div>
              {/* 이 두 값은 업태를 가리지 않은 «음식점 전체»다 — 위의 업태별
                  칸과 이름이 겹치지 않게 «음식점»으로 부른다. */}
              <div className={s.vs}>
                <div className={s.vsGreen}>
                  <span>영업 중인 음식점</span>
                  <strong>
                    {d.competition.shopsHere !== null ? `${int(d.competition.shopsHere)}곳` : "정보 없음"}
                  </strong>
                  <em>오래 버틴 가게가 많다는 뜻이에요</em>
                </div>
                <div className={s.vsOrange}>
                  <span>지금까지 연 음식점</span>
                  <strong>
                    {d.competition.openingsTotal !== null ? `${int(d.competition.openingsTotal)}곳` : "정보 없음"}
                  </strong>
                  <em>지금까지 이 자리를 거쳐 간 가게 수예요</em>
                </div>
              </div>
            </section>

            <section className={s.card} data-reveal>
              <div className={s.cardHead}>
                <h2>미리 알아두세요</h2>
              </div>
              {/* Only actual risks earn a row — «이 자리의» 위험만 담고 모델
                  일반론은 담지 않는다. 하드코딩한 AUC 를 여기 적었던 적이
                  있는데, 값이 바뀌면 화면 두 곳이 갈라지는 자리였다.
                  모델 한계를 다시 실으려면 `meta().caveats` 를 쓴다. */}
              <div className={s.risks}>
                {search.rentMonthly === null ? (
                  <RiskRow level="high" title="임대료를 아직 안 넣으셨어요" desc="손익·권리금 탭에서 넣으면 손익까지 계산해 드려요." />
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

          {/* ── 실질 월 점유비용 ─────────────────────────────────
              월세·보증금·권리금을 한 숫자로 합친다. 임대료 입력은 위 손익
              카드와 공유한다 — 두 번 입력시키지 않는다.
              기획서 §3 은 이 카드를 손익보다 «먼저» 두라고 했다(합친 비용이
              손익의 정직한 분모라는 이유). 2026-08-02 사용자 지시로 순서를
              뒤집었으므로, 되돌릴 때 그 근거부터 다시 읽을 것. */}
          <OccupancyCostCard
            gridId={d.gridId}
            uptae={uptae}
            sales={d.sales}
            rentMonthly={search.rentMonthly}
            onRentChange={(v) => search.set({ rentMonthly: v })}
            onSuccession={setSuccession}
          />

          {/* 위 카드가 승계 확률을 «계산한 뒤에» 이어서 뜬다. 붙여 두는 이유가
              있다 — «이어받을 사람이 적다» 는 사실과 «그래서 무엇을 하면 되나»
              가 떨어져 있으면 앞의 숫자가 겁만 주고 끝난다. */}
          <KbLinkCard successionProb={succession} />

          {/* ── 권리금 진입 카드 — 리포트 본체는 다이얼로그로 ────── */}
          <section className={s.card} data-reveal>
            <div className={s.cardHead}>
              <h2>부르는 권리금, 적당한가요?</h2>
              <p>이 자리 기록으로 참고가를 계산해 드려요. 감정평가는 아니에요.</p>
            </div>
            {/* 막는 이유가 둘이고 서로 다른 말이 필요하다 — 업종에 비교할
                벤치마크가 없는 것(어느 자리든 불가)과, 이 격자에 매출 근거가
                없는 것(다른 자리면 가능). 업종 쪽을 먼저 본다.
                두 경우 다 «실패»가 아니라 답이므로 오류로 그리지 않는다. */}
            {meta && !meta.goodwillSupportedUptae.includes(uptae) ? (
              // 업태명을 조사 앞에 넣으면 «기타은(는)»이 된다. 받침 유무가
              // 업태마다 다르고 「외국음식전문점(인도,태국등)」처럼 괄호로
              // 끝나기도 해서 규칙으로 못 푼다. 업태는 이미 상단 배지에 있으니
              // 조사 자리에서 뺀다.
              <p className={s.gwNone}>
                선택하신 업종은 비교할 서울 업종 평균이 없어서 참고가를 계산하지 않아요. 다른 업종의
                평균을 대신 쓰면 근거 없는 숫자가 되거든요.
              </p>
            ) : d.sales.available ? (
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
          {/* 맨 위 — 아래 표들을 먼저 말로 풀어 준다. active 를 넘기는 이유는
              패널이 숨겨져도 마운트되기 때문이다(안 걸면 상세를 열 때마다
              읽지도 않을 요약에 LLM 호출이 나간다). */}
          <AiSummaryCard gridId={d.gridId} uptae={uptae} active={tab === "dataTab"} />

          {/* ── buildings in this cell (resolution ladder v1 — FACTS) ── */}
          <BuildingsSection gridId={d.gridId} uptae={uptae} />

          {/* ── observed by grade (figma 매물 slot → real table) ──── */}
          <section className={s.card} data-reveal>
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
            <section className={s.card} data-reveal>
              <div className={s.cardHead}>
                {/* 제목이 2년 열을 빼먹고 있었다. 열에 있는 것을 제목에서
                    지우지 않는다.
                    3년을 헤드라인으로 두는 근거는 계약 실태다 — 중기부·소진공
                    2025 상가건물임대차 실태조사에서 임차인 평균 계약기간이
                    42.2개월(약 3.5년)이다. «임차는 보통 1~2년» 은 최초 계약의
                    인상이고, 갱신요구권까지 포함한 실제 체류는 3년대다. */}
                <h2>1년, 2년, 3년, 5년 뒤에는</h2>
                <p>계약기간을 고르면 그 기간의 실측이 진해져요. 등급은 그대로예요.</p>
              </div>
              <div className={s.leaseSeg} role="group" aria-label="계약기간 선택">
                {([1, 2, 3] as const).map((y) => (
                  <button
                    key={y}
                    type="button"
                    className={y === leaseYears ? `${s.leaseBtn} ${s.leaseBtnOn}` : s.leaseBtn}
                    onClick={() => setLeaseYears(y)}
                  >
                    {y}년{y === 3 ? " 이상" : ""} 계약
                  </button>
                ))}
              </div>
              <LeaseLead meta={meta} grade={d.grade} years={leaseYears} />
              <PeriodTable meta={meta} grade={d.grade} focusYears={leaseYears} />
              <p className={s.tableFoot}>
                * 5년 숫자는 다른 시기({periodOf(meta, 5)?.cohort ?? "별도"})에 연 가게들 기준이라 1·2·3년과
                이어서 읽으면 안 돼요.
              </p>
            </section>
          ) : null}

          {/* ── grade × area (observed, not causal — §5-6) ─────────── */}
          {meta?.gradeArea ? (
            <section className={s.card} data-reveal>
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
          <a
            className={s.loan}
            href={KB_LOAN_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            <span className={s.loanTag}>KB 창업자금 대출</span>
            <h3>이 분석 그대로 대출 상담까지</h3>
            <ul className={s.loanList}>
              <li>함께 전달되는 것 · 입지 등급</li>
              <li>등급별 실제 3년 생존율</li>
              <li>입력한 조건의 손익 계산 결과</li>
            </ul>
            <span className={s.loanCap}>한도·금리 시뮬레이션은 제공하지 않습니다.</span>
          </a>

          <a
            className={s.coach}
            href={KB_CONSULTING_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            <span className={s.coachTag}>전문가 최종 코칭</span>
            <p>이 리포트와 함께 KB 소상공인 컨설팅 전문가와 최종 점검을 이어갈 수 있어요.</p>
            <div className={s.coachChips}>
              <span>상권 분석</span>
              <span>창업 일반</span>
              <span>금융 상담</span>
              <span>경영 상담</span>
            </div>
          </a>

          <ChangesCard gridId={d.gridId} uptae={uptae} />
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

/** 직전 채점 판과 견준 이 자리의 변동.
 *
 *  네 상태를 «전부 다르게» 보여야 한다 — 견줄 판이 없음 / 그대로임 /
 *  자리가 변함 / 우리가 기준을 바꿈. 마지막 것을 «등급이 내렸어요»로 뭉개면
 *  사용자 자리는 그대로인데 나빠졌다고 알리는 셈이 된다.
 *
 *  실패는 본문을 깨뜨리지 않는다 — 이건 사이드바의 부가 정보이고, 여기서
 *  전면 에러를 띄우면 리포트가 멀쩡한데도 화면이 고장난 것처럼 보인다.
 *  다만 «못 불러왔다»와 «변동이 없다»는 다른 사실이라 카드 안에서 구분해 말한다. */
function ChangesCard({ gridId, uptae }: { gridId: string; uptae: string }) {
  const q = useQuery({
    queryKey: ["changes", gridId, uptae],
    queryFn: () => api.changes(gridId, uptae),
    staleTime: Infinity,
    retry: 0,
  });
  if (q.isPending) return null;
  if (q.isError) {
    return (
      <div className={s.alarm}>
        <strong>이 자리, 그새 달라졌나요?</strong>
        <p>
          변동 기록을 불러오지 못했어요.{" "}
          <button type="button" className={s.alarmRetry} onClick={() => q.refetch()}>
            다시 시도
          </button>
        </p>
      </div>
    );
  }

  const { available, event, sentence, baselineAsOf, currentAsOf, history } = q.data;
  return (
    <div className={s.alarm}>
      <strong>이 자리, 그새 달라졌나요?</strong>
      {!available ? (
        <p>아직 견줄 이전 기록이 없어요. 다음 갱신부터 비교해 드릴게요.</p>
      ) : !event ? (
        <p>
          {baselineAsOf} 이후 등급은 그대로예요.
        </p>
      ) : (
        <>
          <p className={event.kind === "recalibration" ? s.alarmNote : s.alarmMoved}>
            {sentence}
          </p>
          <span className={s.alarmFoot}>
            {baselineAsOf} → {currentAsOf} 두 판을 견줬어요
          </span>
        </>
      )}
      {/* 한 문장 알림 아래 10년 추이. 등급이 아니라 실제 개·폐업이다 — 등급은
          상대 순위라 남이 움직여도 바뀌고, 그걸 선으로 그리면 순위 요동이 추세로
          읽힌다(docs: service/alerts.py 상단 실측). */}
      {history ? <ChangeHistoryChart history={history} /> : null}
    </div>
  );
}

/** Building records inside this 100m cell (goodwill-report-design §5 ladder).
 *  FACTS from licence rows grouped by parcel — the sort is "most active shops",
 *  a factual order, and the mandatory label says this is not a validated
 *  prediction. Never rank or score buildings here. */
function BuildingsSection({ gridId, uptae }: { gridId: string; uptae: string }) {
  const q = useQuery({
    queryKey: ["buildings", gridId],
    queryFn: () => api.buildings(gridId),
    staleTime: Infinity,
  });

  return (
    <section className={s.card} data-reveal>
      <div className={s.cardHead}>
        <h2>이 자리의 건물 기록</h2>
        <p>이 자리 안 건물들에서 실제로 있었던 일이에요 · 영업 중인 가게가 많은 순</p>
      </div>
      {q.isPending ? (
        <Loading label="건물 기록을 세는 중…" />
      ) : q.isError ? (
        <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} />
      ) : q.data.buildings.length === 0 ? (
        <p className={s.bldgEmpty}>이 자리 안에서 가게를 연 기록이 아직 없어요.</p>
      ) : (
        <div className={s.bldgList}>
          {q.data.buildings.map((b) => (
            <div key={b.jibun} className={s.bldgRow}>
              <div className={s.bldgId}>
                <strong>{b.buildingName ?? shortJibun(b.jibun)}</strong>
                {b.buildingName ? <span>{shortJibun(b.jibun)}</span> : null}
              </div>
              <div className={s.bldgStats}>
                <em>영업 중 {int(b.activeShops)}곳</em>
                <span>
                  지금까지 연 {int(b.openingsTotal)}곳 · 닫은 {int(b.closuresTotal)}곳
                </span>
              </div>
              <div className={s.bldgMix}>
                {b.uptaeMix.map((m) => (
                  <span key={m.uptae} className={m.uptae === uptae ? s.bldgChipOn : s.bldgChip}>
                    {m.uptae} {int(m.active)}곳
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      {q.data && q.data.unparsedCount > 0 ? (
        <p className={s.tableFoot}>주소를 확인할 수 없는 기록 {int(q.data.unparsedCount)}건은 세지 않았어요.</p>
      ) : null}
      <p className={s.tableFoot}>
        * 건물 정보는 인허가 기록을 그대로 센 사실이고, 등급 같은 검증된 예측이 아니에요.
      </p>
    </section>
  );
}

/** "서울특별시 영등포구 여의도동 27-2" → "영등포구 여의도동 27-2" */
function shortJibun(jibun: string): string {
  return jibun.replace(/^서울특별시\s*/, "");
}

/** grade → holdout band row (1 = top band, 9 = bottom, rest middle). */
function bandIndex(grade: number): number {
  return grade === 1 ? 0 : grade === 9 ? 2 : 1;
}

function periodOf(meta: Meta, years: 1 | 2 | 3 | 5) {
  return meta.survivalByPeriod.find((p) => p.years === years) ?? null;
}

/** 1·2·3y share the 2023 cohort; 5y is a separate fit and gets a starred column
 *  instead of a shared axis (serving-design §5-5). 2y is here because shop
 *  leases are commonly 1-2 years, so it is the horizon most tenants actually
 *  ask about — and it carries the largest sample (the 2023 cohort is fully
 *  judged at 2 years but only half-judged at 3). */
/** One sentence answering the user's actual question — «내 계약기간 동안
 *  이 밴드 자리들은 실제로 얼마나 남았나». Reads the same holdout bands the
 *  table shows; renders nothing when the band shape is not the 3-band one. */
function LeaseLead({ meta, grade, years }: { meta: Meta; grade: number; years: 1 | 2 | 3 }) {
  const p = periodOf(meta, years);
  const bands = p?.bands ?? null;
  const b = bands && bands.length === 3 ? bands[bandIndex(grade)] : null;
  if (!b || b.survival === null || b.survival === undefined) return null;
  return (
    <p className={s.leaseLead}>
      {years}년{years === 3 ? " 이상" : ""} 계약이면 — 이 자리 밴드({b.band})는 실제로{" "}
      <b>{pct1(b.survival)}</b>가 남았어요.
    </p>
  );
}

function PeriodTable({
  meta,
  grade,
  focusYears,
}: {
  meta: Meta;
  grade: number;
  focusYears?: 1 | 2 | 3;
}) {
  const periods = ([1, 2, 3, 5] as const).map((y) => periodOf(meta, y));
  const bandLabels = periods.find((p) => p?.bands)?.bands?.map((b) => b.band) ?? [];
  if (bandLabels.length === 0) return null;
  return (
    <table className={s.table}>
      <thead>
        <tr>
          <th>밴드</th>
          {periods.map((p, i) =>
            p?.bands ? (
              <th key={i} className={p.years === focusYears ? s.colOn : undefined}>
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
                  <td key={i} className={p.years === focusYears ? s.colOn : undefined}>
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
            p?.bands ? (
              <td key={i} className={p.years === focusYears ? s.colOn : undefined}>
                {p.overall !== null ? pct1(p.overall) : "정보 없음"}
              </td>
            ) : null,
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
