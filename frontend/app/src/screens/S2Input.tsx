import { useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { api } from "../api/client";
import CaveatStrip from "../components/CaveatStrip";
import Nav from "../components/Nav";
import { ErrorState, Loading } from "../components/states";
import { int, uptaeLabel } from "../lib/format";
import { isRecommendable } from "../lib/grade";
import { useSearch } from "../state/search";
import s from "./S2Input.module.css";

// S2, rebuilt against figma-snapshot S2 (STEP boxes + dark summary panel).
// Differences from the mockup are data-honesty, not layout: STEP 4 창업자
// 프로필 is not collected (nothing in the model consumes it), the funnel shows
// live API counts instead of 12,480→842→24, and the 가중치 note states what is
// actually precomputed. 예산 sliders feed the S4 money tab (runway/occupancy
// inputs) only — they never filter.

const UPFRONT = { min: 0, max: 20000, step: 100 }; // 만원
const RENT = { min: 0, max: 600, step: 10 }; // 만원/월

export default function S2Input({ go }: { go: (s: Screen) => void }) {
  const search = useSearch();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });

  // Live funnel: same key S3 uses, so 분석 시작 lands on a warm cache.
  const rec = useQuery({
    queryKey: ["recommend", search.uptae, search.districts],
    queryFn: () => api.recommend(search.uptae!, search.districts),
    enabled: search.uptae !== null,
  });
  // Same threshold S3 applies — the funnel must promise the count S3 shows.
  const passing = rec.data ? rec.data.items.filter(isRecommendable).length : null;
  const firstPass = rec.data?.items.find(isRecommendable);

  return (
    <div className={s.page}>
      <Nav step={1} onHome={() => go({ name: "landing" })} />
      <main className={s.body}>
        {/* ── left: form ─────────────────────────────────────────────── */}
        <div className={s.form}>
          <header className={s.head}>
            <h1>어떤 가게를 여시나요?</h1>
            <p>업종만 골라도 바로 볼 수 있어요.</p>
          </header>

          <div className={s.sheet}>
          {/* STEP 1 · 업종 — the only required input comes first (UX critique:
              the old budget-first order contradicted "업종만 필수" copy) */}
          <section className={s.step}>
            <div className={s.boxHead}>
              <div className={s.boxTitleRow}>
                <span className={s.stepTag}>STEP 1</span>
                <h2>업종</h2>
              </div>
            </div>
            {meta.isPending ? (
              <Loading />
            ) : meta.isError ? (
              <ErrorState onRetry={() => meta.refetch()} detail={String(meta.error)} />
            ) : (
              <>
                <div className={s.chips}>
                  {/* value 는 meta().uptae 그대로(DB 키), 표기만 uptaeLabel 로 교정한다. */}
                  {meta.data.uptae.map((u) => (
                    <button
                      key={u}
                      className={search.uptae === u ? s.chipOn : s.chip}
                      onClick={() => search.set({ uptae: u })}
                    >
                      {uptaeLabel(u)}
                    </button>
                  ))}
                </div>
                <div className={s.note}>
                  <strong>선택한 업종 기준</strong>
                  <span>
                    {/* The counts are scope-wide and barely move between 업종
                        — the top-1 dong is what visibly reacts to the chips. */}
                    {search.uptae
                      ? rec.data && passing !== null
                        ? `${uptaeLabel(search.uptae)} 자리 ${int(rec.data.inScope)}곳 중 ${int(passing)}곳을 추천해요${
                            firstPass?.admDong ? ` · 지금 1순위는 ${firstPass.admDong}` : ""
                          }`
                        : rec.isPending
                          ? "후보 세는 중…"
                          : "후보 수를 불러오지 못했어요"
                      : "업종을 고르면 후보가 바로 나와요"}
                  </span>
                </div>
              </>
            )}
          </section>

          {/* STEP 2 · 범위 */}
          <section className={s.step}>
            <div className={s.boxHead}>
              <div className={s.boxTitleRow}>
                <span className={s.stepTag}>STEP 2</span>
                <h2>어느 동네까지 볼까요?</h2>
              </div>
              <p>여러 구를 같이 골라도 돼요.</p>
            </div>
            {meta.data ? (
              <div className={s.chips}>
                <button
                  className={search.districts.length === 0 ? s.chipOn : s.chip}
                  onClick={() => search.set({ districts: [] })}
                >
                  서울 전역
                </button>
                {meta.data.districts.map((d) => (
                  <button
                    key={d}
                    className={search.districts.includes(d) ? s.chipOn : s.chip}
                    onClick={() => search.toggleDistrict(d)}
                  >
                    {d}
                  </button>
                ))}
              </div>
            ) : null}
          </section>

          {/* STEP 3 · 예산 (선택) — optional inputs go last */}
          <section className={s.step}>
            <div className={s.boxHead}>
              <div className={s.boxTitleRow}>
                <span className={s.stepTag}>STEP 3 (선택)</span>
                <h2>예산도 넣어볼까요?</h2>
              </div>
              <p>넣으면 손익까지 계산해 드려요. 추천 순위와는 무관해요.</p>
            </div>
            <BudgetSlider
              label="초기투자 총액"
              hint="보증금 + 권리금 + 인테리어 합산"
              cfg={UPFRONT}
              value={search.upfront}
              onChange={(v) => search.set({ upfront: v })}
              format={(v) => `${int(v)}만 원`}
              rangeLabel={["0", "2억"]}
            />
            <BudgetSlider
              label="월 임대료"
              hint=""
              cfg={RENT}
              value={search.rentMonthly}
              onChange={(v) => search.set({ rentMonthly: v })}
              format={(v) => `${int(v)}만 원`}
              rangeLabel={["0", "600만"]}
            />
          </section>
          </div>
        </div>

        {/* ── right: dark summary panel ──────────────────────────────── */}
        <aside className={s.side}>
          <div className={s.summary}>
            <p className={s.summaryTitle}>입력한 조건</p>
            <dl className={s.kv}>
              <div>
                <dt>업종</dt>
                <dd>{search.uptae !== null ? uptaeLabel(search.uptae) : "미선택"}</dd>
              </div>
              <div>
                <dt>범위</dt>
                <dd>
                  {search.districts.length === 0
                    ? "서울 전역"
                    : search.districts.length <= 2
                      ? search.districts.join(" · ")
                      : `${search.districts.length}개 자치구`}
                </dd>
              </div>
              <div>
                <dt>초기투자</dt>
                <dd>{search.upfront === null ? "미입력" : `${int(search.upfront)}만 원`}</dd>
              </div>
              <div>
                <dt>월 임대료</dt>
                <dd>{search.rentMonthly === null ? "미입력" : `${int(search.rentMonthly)}만 원`}</dd>
              </div>
            </dl>

            <hr className={s.rule} />

            <div className={s.funnel}>
              <div>
                <span>서울 전체 자리</span>
                <strong className={s.fDim}>{meta.data ? `${int(meta.data.gridCount)}곳` : "…"}</strong>
              </div>
              <div className={search.districts.length === 0 ? s.funnelStack : undefined}>
                <span>고른 동네의 자리</span>
                {/* 서울 전역이면 inScope === gridCount — repeating the same
                    number twice reads as broken (owner report). A funnel row
                    that is not narrowing shows a hint, not a number. */}
                {search.districts.length === 0 ? (
                  <strong className={s.fHint}>동네를 고르면 좁혀져요</strong>
                ) : (
                  <strong>
                    {!search.uptae
                      ? "업종 선택 후"
                      : rec.data
                        ? `${int(rec.data.inScope)}곳`
                        : rec.isError
                          ? "불러오지 못함"
                          : "…"}
                  </strong>
                )}
              </div>
              <div>
                <span>상위 추천 후보</span>
                <strong className={s.fY}>
                  {search.uptae && passing !== null ? `${int(passing)}곳` : rec.isError ? "—" : "…"}
                </strong>
              </div>
            </div>

            <button className={s.cta} disabled={!search.uptae} onClick={() => go({ name: "results" })}>
              추천 자리 보기
            </button>
          </div>
          <p className={s.caption}>결과는 참고 정보이며 최종 판단은 사용자에게 있습니다.</p>
        </aside>
      </main>
      <CaveatStrip />
    </div>
  );
}

/** Figma budget slider — yellow fill track, 만원 value on the right.
 *  null = untouched; the first drag sets a value, 지우기 resets to null. */
function BudgetSlider({
  label,
  hint,
  cfg,
  value,
  onChange,
  format,
  rangeLabel,
}: {
  label: string;
  hint: string;
  cfg: { min: number; max: number; step: number };
  value: number | null;
  onChange: (v: number | null) => void;
  format: (v: number) => string;
  rangeLabel: [string, string];
}) {
  const v = value ?? cfg.min;
  const fillPct = ((v - cfg.min) / (cfg.max - cfg.min)) * 100;
  return (
    <div className={s.slider}>
      <div className={s.sliderTop}>
        <span className={s.sliderLabel}>
          {label}
          {hint ? <em>{hint}</em> : null}
        </span>
        <span className={s.sliderValue}>
          {value === null ? "미입력" : format(value)}
          {value !== null ? (
            <button className={s.sliderClear} onClick={() => onChange(null)}>
              지우기
            </button>
          ) : null}
        </span>
      </div>
      <input
        type="range"
        min={cfg.min}
        max={cfg.max}
        step={cfg.step}
        value={v}
        aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
        className={s.range}
        style={{
          background: `linear-gradient(to right, var(--fg-y) ${fillPct}%, #edebe6 ${fillPct}%)`,
        }}
      />
      <div className={s.rangeEnds}>
        <span>{rangeLabel[0]}</span>
        <span>{rangeLabel[1]}</span>
      </div>
    </div>
  );
}
