import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { api } from "../api/client";
import CaveatStrip from "../components/CaveatStrip";
import Nav from "../components/Nav";
import { ErrorState, Loading } from "../components/states";
import { int } from "../lib/format";
import { useSearch } from "../state/search";
import s from "./S2Input.module.css";
import ui from "../styles/ui.module.css";

// S2 조건 입력 — spec: ui-spec.md §3-S2 (P0).
// The mockup's STEP 1~4 form is dismantled (§0 원칙 3): required inputs are
// 업종 + 범위 and nothing else. 예산 is one collapsed row; 매출·마진·면적 are
// inline inputs on S4. 창업자 프로필 is deleted outright — none of it reaches
// the model, so collecting it would be pretending to use it.
export default function S2Input({ go }: { go: (s: Screen) => void }) {
  const search = useSearch();
  const [budgetOpen, setBudgetOpen] = useState(false);
  const q = useQuery({ queryKey: ["meta"], queryFn: api.meta });

  return (
    <>
      <Nav step={1} onHome={() => go({ name: "landing" })} />
      <main className={s.body}>
        <div className={s.form}>
          <header className={s.head}>
            <h1 className={ui.sectionTitle}>어떤 가게를, 어디에 내시나요?</h1>
            <p className={ui.lead}>
              업종과 지역만 고르면 결과가 나옵니다. 예산은 나중에 넣어도 됩니다.
            </p>
          </header>

          {q.isPending ? (
            <Loading />
          ) : q.isError ? (
            <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} />
          ) : (
            <>
              <section className={ui.card}>
                <h2 className={s.boxTitle}>업종</h2>
                <p className={s.boxHint}>업종마다 별도 스코어를 미리 계산해 두었습니다.</p>
                <div className={s.chips}>
                  {/* meta().uptae verbatim — trimming "외국음식전문점" to "외국음식"
                      breaks the DB key and the lookup fails silently (§7). */}
                  {q.data.uptae.map((u) => (
                    <button
                      key={u}
                      className={search.uptae === u ? ui.chipOn : ui.chip}
                      onClick={() => search.set({ uptae: u })}
                    >
                      {u}
                    </button>
                  ))}
                </div>
              </section>

              <section className={ui.card}>
                <h2 className={s.boxTitle}>지역</h2>
                <p className={s.boxHint}>자치구 25곳 전부를 다룹니다. 여러 곳을 함께 고를 수 있습니다.</p>
                <div className={s.chips}>
                  <button
                    className={search.districts.length === 0 ? ui.chipOn : ui.chip}
                    onClick={() => search.set({ districts: [] })}
                  >
                    서울 전역
                  </button>
                  {q.data.districts.map((d) => (
                    <button
                      key={d}
                      className={search.districts.includes(d) ? ui.chipOn : ui.chip}
                      onClick={() => search.toggleDistrict(d)}
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </section>
            </>
          )}

          <section className={ui.card}>
            <button className={s.accordion} onClick={() => setBudgetOpen((v) => !v)}>
              <span>예산도 입력하면 손익까지 계산합니다</span>
              <span className={s.accordionMark}>{budgetOpen ? "−" : "+"}</span>
            </button>
            {budgetOpen ? (
              <div className={s.budget}>
                <MoneyField
                  label="초기투자 총액"
                  hint="보증금 + 권리금 + 인테리어를 합한 금액"
                  value={search.upfront}
                  onChange={(v) => search.set({ upfront: v })}
                />
                <MoneyField
                  label="월 임대료"
                  hint="임대료는 매물마다 달라 데이터로 채울 수 없습니다"
                  value={search.rentMonthly}
                  onChange={(v) => search.set({ rentMonthly: v })}
                />
              </div>
            ) : null}
          </section>
        </div>

        <aside className={s.summary}>
          <div className={ui.cardDark}>
            <p className={s.summaryTitle}>입력한 조건</p>
            <dl className={s.kv}>
              <div>
                <dt>업종</dt>
                <dd>{search.uptae ?? "미선택"}</dd>
              </div>
              <div>
                <dt>지역</dt>
                <dd>
                  {search.districts.length === 0
                    ? "서울 전역"
                    : `${search.districts.length}개 자치구`}
                </dd>
              </div>
              <div>
                <dt>월 임대료</dt>
                <dd>{search.rentMonthly === null ? "미입력" : `${int(search.rentMonthly)}만`}</dd>
              </div>
            </dl>

            <hr className={s.rule} />

            {/* Funnel row 1 is a real API value. Rows 2-3 are only knowable
                after the query runs — saying so beats inventing 12,480→842. */}
            <div className={s.funnel}>
              <div>
                <span>서울 전체 격자</span>
                <strong>{q.data ? `${int(q.data.gridCount)}개` : "—"}</strong>
              </div>
              <div>
                <span>범위 내 격자</span>
                <strong className={s.pending}>분석하면 확인됩니다</strong>
              </div>
            </div>

            <button
              className={s.cta}
              disabled={!search.uptae}
              onClick={() => go({ name: "results" })}
            >
              분석 시작
            </button>
            {!search.uptae ? <p className={s.ctaHint}>업종을 골라주세요</p> : null}
          </div>
        </aside>
      </main>
      <CaveatStrip />
    </>
  );
}

/** 만원 단위 입력. Empty stays null — never coerced to 0 (§4). */
function MoneyField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <label className={s.money}>
      <span className={s.moneyLabel}>{label}</span>
      <span className={s.moneyInput}>
        <input
          type="number"
          min={0}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          placeholder="0"
        />
        <span className={s.moneyUnit}>만원</span>
      </span>
      <span className={ui.captionBlock}>{hint}</span>
    </label>
  );
}
