import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Screen } from "../App";
import Dropdown from "../components/Dropdown";
import { useSearch } from "../state/search";
import { FEATURES_3, PROVENANCE, SOURCES, TEAM } from "../copy";
import { int, pct0 } from "../lib/format";
import s from "./S1Landing.module.css";

// S1 landing, rebuilt 1:1 against figma-snapshot S1 (2026-07-27 direction:
// match the mockup layout first, carve details later). Structure = mockup;
// copy/numbers = ui-spec §3-S1 replacement table + live meta(). The mockup's
// fabricated numbers (12,480 blocks, 20s, SNS claims) never render here.

export default function S1Landing({ go }: { go: (s: Screen) => void }) {
  const search = useSearch();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });

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
          <span className={s.mark}>P</span>
          <span className={s.wordmark}>KB Previl</span>
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
          어디에 낼지,
          <br />
          <em>그 자리의 기록을 보고 정하세요</em>
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

        {/* proof stats — the killer numbers, promoted out of body small-print
            (UX critique #3). All live: provenance consts + meta(). */}
        <div className={s.stats}>
          <div className={s.stat}>
            <strong>{PROVENANCE.recordCount}</strong>
            <span>개업·폐업 기록 ({PROVENANCE.recordSince})</span>
          </div>
          <i className={s.statDivider} />
          <div className={s.stat}>
            <strong>{meta.data ? int(meta.data.gridCount) : "…"}</strong>
            <span>분석한 서울의 자리</span>
          </div>
          <i className={s.statDivider} />
          <div className={s.stat}>
            <strong>
              {top && bottom ? `${pct0(top.survival)} vs ${pct0(bottom.survival)}` : "…"}
            </strong>
            <span>1등급과 10등급의 실제 3년 생존율</span>
          </div>
        </div>

        <p className={s.sources}>{SOURCES.join("  ·  ")}</p>
      </header>

      {/* ── WHY NOW ──────────────────────────────────────────────────── */}
      <section className={s.why} ref={why}>
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
      <section className={s.what} ref={features}>
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
      <section className={s.differs} ref={differs}>
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
      <section className={s.cta}>
        <h2 className={s.ctaH}>업종 하나만 준비하세요</h2>
        <button className={s.ctaBtn} onClick={start}>
          무료로 자리 찾기 →
        </button>
      </section>

      {/* ── Footer (dark) ────────────────────────────────────────────── */}
      <footer className={s.footer}>
        <span>
          KB Previl · AI 상권·입지 참모&nbsp;&nbsp;|&nbsp;&nbsp;{TEAM.join(" · ")}
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
