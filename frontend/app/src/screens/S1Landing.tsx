import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Screen } from "../App";
import Dropdown from "../components/Dropdown";
import { useSearch } from "../state/search";
import { FEATURES_3, PROVENANCE, SOURCES, TEAM } from "../copy";
import { int, pct0, splitUnit } from "../lib/format";
import { useReveal } from "../lib/reveal";
import s from "./S1Landing.module.css";
import markUrl from "../assets/previl-mark.png";

/** 히어로 지표 한 칸. 수치는 크게, 단위는 작게 — 자릿수가 먼저 읽힌다.
 *  단위로 안 갈라지는 값("77% vs 28%")은 splitUnit 이 통째로 돌려주므로
 *  여기서 따로 분기하지 않는다. */
function Metric({ v }: { v: string }) {
  const [n, u] = splitUnit(v);
  return (
    <strong>
      {n}
      {u ? <i>{u}</i> : null}
    </strong>
  );
}

// S1 landing, rebuilt 1:1 against figma-snapshot S1 (2026-07-27 direction:
// match the mockup layout first, carve details later). Structure = mockup;
// copy/numbers = ui-spec §3-S1 replacement table + live meta(). The mockup's
// fabricated numbers (12,480 blocks, 20s, SNS claims) never render here.

export default function S1Landing({ go }: { go: (s: Screen) => void }) {
  const search = useSearch();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  useReveal();

  const features = useRef<HTMLElement>(null);
  const differs = useRef<HTMLElement>(null);
  const why = useRef<HTMLElement>(null);
  const scrollTo = (el: React.RefObject<HTMLElement | null>) =>
    el.current?.scrollIntoView({ behavior: "smooth" });

  const top = meta.data?.observedByGrade.find((g) => g.grade === 1);
  const bottom = meta.data?.observedByGrade.find((g) => g.grade === 10);

  const start = () => go({ name: "input" });

  return (
    <div className={s.page}>
      {/* ── Nav ──────────────────────────────────────────────────────── */}
      <nav className={s.nav}>
        <div className={s.logo}>
          <img className={s.mark} src={markUrl} alt="" />
          <span className={s.wordmark}>
            <span className={s.wordmarkKb}>KB</span> Previl
          </span>
        </div>
        <div className={s.menu}>
          <button onClick={() => scrollTo(why)}>상권 찾기</button>
          <button onClick={() => scrollTo(features)}>서비스 소개</button>
          <button onClick={() => scrollTo(differs)}>데이터·방법론</button>
        </div>
      </nav>

      {/* ── Hero (dark) ──────────────────────────────────────────────── */}
      <header className={s.hero}>
        <h1 className={s.h1}>
          데이터로 성공을 만듭니다
          <br />
          {/* 좁은 폭에서 «KB / Previl» 로 갈라진다 — 한글은 keep-all 이 잡아주지만
              라틴 사이의 공백은 그대로 끊기는 자리라 브랜드명만 묶어준다. */}
          <em>새로운 창업의 시작, KB&nbsp;Previl</em>
        </h1>

        {/* search pill — real inputs feeding the S2 form */}
        <div className={s.searchCard}>
          <div className={s.field}>
            <span className={s.fieldLabel}>업종</span>
            <Dropdown
              options={(meta.data?.uptae ?? []).map((u) => ({ value: u, label: u }))}
              value={search.uptae}
              placeholder="어떤 가게를 내시나요"
              emptyNote={meta.isError ? "목록을 불러오지 못했습니다" : "불러오는 중…"}
              onSelect={(v) => search.set({ uptae: v })}
            />
          </div>
          <i className={s.fieldDivider} />
          <div className={s.field}>
            <span className={s.fieldLabel}>희망 범위</span>
            {/* Multi-district selections (made on S2) cannot round-trip through
                a single-value control — say so instead of silently showing
                only the first one. */}
            <Dropdown
              options={[
                { value: "", label: "서울 전역" },
                ...(meta.data?.districts ?? []).map((d) => ({ value: d, label: d })),
              ]}
              value={search.districts.length === 1 ? search.districts[0] : ""}
              display={
                search.districts.length > 1 ? `${search.districts.length}개 자치구` : undefined
              }
              placeholder="서울 전역"
              onSelect={(v) => search.set({ districts: v ? [v] : [] })}
            />
          </div>
          <i className={s.fieldDivider} />
          <label className={s.field}>
            <span className={s.fieldLabel}>월 임대료 (선택)</span>
            <span className={s.moneyRow}>
              <input
                className={s.fieldValue}
                type="number"
                min={0}
                placeholder="예: 250"
                value={search.rentMonthly ?? ""}
                onChange={(e) =>
                  search.set({ rentMonthly: e.target.value === "" ? null : Number(e.target.value) })
                }
              />
              <span className={search.rentMonthly !== null ? s.unit : s.unitDim}>만원</span>
            </span>
          </label>
          <button className={s.searchBtn} onClick={start}>
            자리 찾기
          </button>
        </div>

        {/* 두 번째 입구 — 기획서 §1.4. 예비창업자 대부분은 «어디가 좋아?»가
            아니라 후보를 이미 손에 쥔 채 «여기 계약해도 되나요»를 묻는다.
            그 사람에게 위 검색창은 처음부터 자기 질문이 아니다. */}
        <button className={s.altEntry} onClick={() => go({ name: "compare" })}>
          이미 본 매물이 있으신가요? <b>월세 말고 실제로 나가는 돈으로 비교해 보기 →</b>
        </button>

        {/* proof stats — the killer numbers, promoted out of body small-print
            (UX critique #3). All live: provenance consts + meta(). */}
        <div className={s.stats}>
          <div className={s.stat}>
            <Metric v={PROVENANCE.recordCount} />
            <span>개업·폐업 기록 ({PROVENANCE.recordSince})</span>
          </div>
          <i className={s.statDivider} />
          <div className={s.stat}>
            <Metric v={meta.data ? int(meta.data.gridCount) : "…"} />
            <span>분석한 서울의 자리</span>
          </div>
          <i className={s.statDivider} />
          <div className={s.stat}>
            <Metric
              v={top && bottom ? `${pct0(top.survival)} vs ${pct0(bottom.survival)}` : "…"}
            />
            <span>1등급과 10등급의 실제 3년 생존율</span>
          </div>
        </div>

        <p className={s.sources}>{SOURCES.join("  ·  ")}</p>

        {/* 히어로가 화면을 정확히 채우면서 «아래에 더 있다»는 신호가 사라졌다.
            장식이 아니라 눌러서 실제로 내려가는 버튼이라 자리값을 한다. */}
        <button className={s.scrollCue} onClick={() => scrollTo(why)}>
          <span>Scroll</span>
          <i />
        </button>
      </header>

      {/* ── WHY NOW ──────────────────────────────────────────────────── */}
      <section className={s.why} ref={why} data-reveal>
        <div className={s.secHead}>
          <h2 className={s.h2}>입지 판단은 아직도 감(勘)에 의존합니다</h2>
          <p className={s.secSub}>자리마다 기록은 쌓여 있는데, 볼 방법이 없었어요.</p>
        </div>
        <div className={s.whyCards}>
          <div className={s.whyCard}>
            <span className={s.whyNum}>01</span>
            <h3>부동산 중개인의 감</h3>
            <p>예비 창업자의 입지 판단은 여전히 소문과 발품에 의존한다</p>
          </div>
          <div className={s.whyCard}>
            <span className={s.whyNum}>02</span>
            <h3>폐업 원인의 큰 축</h3>
            <p>한국 자영업 5년 생존율은 전 업종 최저 수준, 그 중심에 잘못된 입지 선택이 있다</p>
          </div>
        </div>
      </section>

      {/* ── WHAT IT DOES ─────────────────────────────────────────────── */}
      <section className={s.what} ref={features} data-reveal>
        <div className={s.secHead}>
          <h2 className={s.h2}>이 자리에서 몇 집이 버텼는지, 전부 세어봤어요</h2>
        </div>
        <div className={s.featGrid}>
          {FEATURES_3.map((f, i) => (
            <div key={f.title} className={s.featCard}>
              <span className={s.featNum}>{["①", "②", "③"][i]}</span>
              <h3>{f.title}</h3>
              <p>{f.body}</p>
              {i === 0 && top && bottom ? (
                <p className={s.featProof}>
                  1등급 자리는 {pct0(top.survival)}, 10등급 자리는 {pct0(bottom.survival)} 버텼어요
                </p>
              ) : null}
            </div>
          ))}
        </div>
      </section>

      {/* ── HOW IT DIFFERS (dark) ────────────────────────────────────── */}
      <section className={s.differs} ref={differs} data-reveal>
        <div className={s.secHead}>
          <h2 className={s.h2Dark}>동네 설명이 아니라, 자리 추천이에요</h2>
        </div>
        <div className={s.table}>
          <div className={s.tHead}>
            <span>축</span>
            <span>KB bridge 상권분석</span>
            <span className={s.tOurs}>KB Previl (본 서비스)</span>
          </div>
          {DIFF_ROWS(meta.data?.uptae.length ?? null).map(([axis, theirs, ours]) => (
            <div key={axis} className={s.tRow}>
              <span className={s.tAxis}>{axis}</span>
              <span className={s.tTheirs}>{theirs}</span>
              <span className={s.tOursCell}>{ours}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA (yellow) ─────────────────────────────────────────────── */}
      <section className={s.cta} data-reveal>
        <h2 className={s.ctaH}>업종 하나만 준비하세요</h2>
        <button className={s.ctaBtn} onClick={start}>
          무료로 자리 찾기 →
        </button>
      </section>

      {/* ── Footer (dark) ────────────────────────────────────────────── */}
      <footer className={s.footer}>
        <span>
          KB Previl&nbsp;&nbsp;|&nbsp;&nbsp;{TEAM.join(" · ")}
        </span>
        <span className={s.footNote}>
          본 서비스의 등급은 과거 데이터 기반 참고 정보이며 최종 판단은 사용자에게 있습니다.
        </span>
      </footer>
    </div>
  );
}

// Replacements per ui-spec §3-S1 차별점 표: 데이터 row = validation methodology,
// 결과물 row drops 예상매출/생존확률, 해상도 row = what we actually resolve.
// The uptae count follows meta() so the table can't drift from the served list.
const DIFF_ROWS = (uptaeCount: number | null): [string, string, string][] => [
  ["사용 방식", "지역을 먼저 골라야 조회 가능", "업종만 넣으면 자리를 찾아줌"],
  ["근거", "현황 통계", "실제로 버틴 가게들의 기록"],
  ["결과물", "동네 현황 설명", "자리 추천 + 등급 + 실제 생존율"],
  [
    "업종 반영",
    "얕음",
    uptaeCount !== null ? `${uptaeCount}개 업종 각각 따로 평가` : "업종별 각각 따로 평가",
  ],
  ["단위", "행정동", "100m 단위 (서울 전역)"],
  ["성격", "정적 정보 조회", "조건을 바꾸면 결과도 바뀜"],
];
