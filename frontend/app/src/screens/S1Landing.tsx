import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Screen } from "../App";
import { useSearch } from "../state/search";
import { FEATURES_6, PROVENANCE, SOURCES, TEAM } from "../copy";
import { pct0 } from "../lib/format";
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
          <span className={s.mark}>터</span>
          <span className={s.wordmark}>KB 터 · TEO</span>
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
          <em>숫자와 근거로 답합니다</em>
        </h1>
        <p className={s.sub}>
          업종만 고르면 서울 전역 100m 격자에서 자리를 찾아,
          <br />
          {PROVENANCE.recordCount}({PROVENANCE.recordSince})으로 검증한 등급과 실측 3년 생존율로 답합니다.
        </p>

        {/* search pill — real inputs feeding the S2 form */}
        <div className={s.searchCard}>
          <label className={s.field}>
            <span className={s.fieldLabel}>업종</span>
            <select
              className={s.fieldValue}
              value={search.uptae ?? ""}
              onChange={(e) => search.set({ uptae: e.target.value || null })}
            >
              <option value="">{meta.isError ? "목록을 불러오지 못했습니다" : "선택하세요"}</option>
              {meta.data?.uptae.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </label>
          <i className={s.fieldDivider} />
          <label className={s.field}>
            <span className={s.fieldLabel}>희망 범위</span>
            <select
              className={s.fieldValue}
              value={search.districts[0] ?? ""}
              onChange={(e) => search.set({ districts: e.target.value ? [e.target.value] : [] })}
            >
              <option value="">서울 전역</option>
              {meta.data?.districts.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          <i className={s.fieldDivider} />
          <label className={s.field}>
            <span className={s.fieldLabel}>월 임대료 (선택)</span>
            <input
              className={s.fieldValue}
              type="number"
              min={0}
              placeholder="만원"
              value={search.rentMonthly ?? ""}
              onChange={(e) =>
                search.set({ rentMonthly: e.target.value === "" ? null : Number(e.target.value) })
              }
            />
          </label>
          <button className={s.searchBtn} onClick={start}>
            자리 찾기
          </button>
        </div>

        <p className={s.sources}>{SOURCES.join("  ·  ")}</p>
      </header>

      {/* ── WHY NOW ──────────────────────────────────────────────────── */}
      <section className={s.why} ref={why}>
        <div className={s.secHead}>
          <h2 className={s.h2}>입지 판단은 아직도 감(勘)에 의존합니다</h2>
          <p className={s.secSub}>
            유동인구·매출·임대료 데이터가 흩어져 있어 개인이 종합할 수단이 없습니다.
          </p>
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
          <div className={s.whyCard}>
            <span className={s.whyNum}>03</span>
            <h3>금융사의 부실 리스크</h3>
            <p>개인에게는 생계 리스크지만, KB에게는 소상공인 대출 부실로 직결된다</p>
          </div>
        </div>
      </section>

      {/* ── WHAT IT DOES ─────────────────────────────────────────────── */}
      <section className={s.what} ref={features}>
        <div className={s.secHead}>
          <h2 className={s.h2}>뜬 상권이 아니라, 검증된 자리를 잡습니다</h2>
        </div>
        <div className={s.featGrid}>
          {FEATURES_6.map((f, i) => (
            <div key={f.title} className={s.featCard}>
              <span className={s.featNum}>{["①", "②", "③", "④", "⑤", "⑥"][i]}</span>
              <h3>{f.title}</h3>
              <p>{f.body}</p>
              {i === 0 && top && bottom ? (
                <p className={s.featProof}>
                  1등급 자리 실측 {pct0(top.survival)} · 10등급 {pct0(bottom.survival)} (홀드아웃)
                </p>
              ) : null}
            </div>
          ))}
        </div>
      </section>

      {/* ── HOW IT DIFFERS (dark) ────────────────────────────────────── */}
      <section className={s.differs} ref={differs}>
        <div className={s.secHead}>
          <h2 className={s.h2Dark}>조회 도구가 아니라, 결정 엔진입니다</h2>
        </div>
        <div className={s.table}>
          <div className={s.tHead}>
            <span>축</span>
            <span>KB bridge 상권분석</span>
            <span className={s.tOurs}>KB 터 (본 서비스)</span>
          </div>
          {DIFF_ROWS.map(([axis, theirs, ours]) => (
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
          KB 터(TEO) · AI 상권·입지 참모&nbsp;&nbsp;|&nbsp;&nbsp;{TEAM.join(" · ")}
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
const DIFF_ROWS: [string, string, string][] = [
  ["사용 방식", "지역을 먼저 골라야 조회 가능", "업종만 넣으면 역으로 자리를 찾아줌"],
  ["데이터", "정형·공공 데이터 중심", "홀드아웃 백테스트로 검증된 예측"],
  ["결과물", '"이 동네는 이렇습니다" (현황)', '"여기 들어가라 + 등급·실측 생존율" (예측)'],
  ["업종 반영", "얕음", "12개 업태 각각 사전계산된 등급"],
  ["해상도", "행정동 단위", "100m 격자 (서울 전역)"],
  ["성격", "정적 정보 조회", "조건이 바뀌면 결과가 다시 계산되는 동적 엔진"],
];
