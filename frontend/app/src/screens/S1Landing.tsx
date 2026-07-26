import { useQuery } from "@tanstack/react-query";
import type { Screen } from "../App";
import { api } from "../api/client";
import Nav from "../components/Nav";
import { ErrorState, Loading } from "../components/states";
import { FEATURES, PROVENANCE, SOURCES } from "../copy";
import { useSearch } from "../state/search";
import s from "./S1Landing.module.css";
import ui from "../styles/ui.module.css";

// S1 랜딩 — spec: frontend/design/ui-spec.md §3-S1 (P0).
// hero + 정직성 스트립 + 기능 카드 3장. Copy comes from the spec's replacement
// table — the Figma snapshot numbers are mock and must not be used.
// Only ONE dark surface in the product lives here (§0 슬롭 표).
export default function S1Landing({ go }: { go: (s: Screen) => void }) {
  return (
    <main>
      <header className={s.hero}>
        <Nav dark />
        <div className={s.heroBody}>
          <span className={s.badge}>제8회 Future Finance AI Challenge</span>
          <h1 className={s.title}>
            어디에 낼지,
            <br />
            <em className={s.titleAccent}>검증된 데이터로</em> 답합니다
          </h1>
          <p className={s.sub}>
            {PROVENANCE.recordSince} 쌓인 {PROVENANCE.recordCount}에서 뽑아,
            뒷 기간({PROVENANCE.validationWindow})으로 따로 검증한 입지 등급입니다.
            그 등급을 받은 자리들이 <strong>실제로 얼마나 살아남았는지</strong>를 함께 보여드립니다.
          </p>
          <UptaeEntry go={go} />
          <p className={s.sources}>{SOURCES.join("  ·  ")}</p>
        </div>
      </header>

      <HonestyStrip />

      <section className={s.features}>
        <p className={ui.eyebrow}>WHAT IT DOES</p>
        <h2 className={ui.sectionTitle}>확률을 말하지 않고, 실측을 보여드립니다</h2>
        {/* Size hierarchy breaks the uniform 6-card grid the mockup had (§0). */}
        <div className={s.featureGrid}>
          {FEATURES.map((f, i) => (
            <article key={f.title} className={i === 0 ? s.featureLead : s.feature}>
              <span className={s.featureNum}>{`0${i + 1}`}</span>
              <h3 className={ui.cardTitle}>{f.title}</h3>
              <p className={ui.body}>{f.body}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

/**
 * The hero asks for ONE thing (업종); 범위 and budget belong to S2 (§0 원칙 3).
 * The list is meta().uptae rendered verbatim — a prettified label would not
 * match the DB key and the lookup would fail silently (§7).
 */
function UptaeEntry({ go }: { go: (s: Screen) => void }) {
  const { uptae, set } = useSearch();
  const q = useQuery({ queryKey: ["meta"], queryFn: api.meta });

  return (
    <div className={s.searchCard}>
      <label className={s.field}>
        <span className={s.fieldLabel}>업종</span>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} />
        ) : (
          <select
            className={s.select}
            value={uptae ?? ""}
            onChange={(e) => set({ uptae: e.target.value || null })}
          >
            <option value="">선택하세요</option>
            {q.data.uptae.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        )}
      </label>
      <button className={ui.btnPrimary} disabled={!uptae} onClick={() => go({ name: "input" })}>
        자리 찾기
      </button>
    </div>
  );
}

/**
 * 정직성 스트립 (ui-spec §3-S1 신규 행): the weakness stated up front, as a
 * trust device. Wording is meta().caveats — never restated in the client, so a
 * rescored model updates this line by itself.
 */
function HonestyStrip() {
  const q = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  return (
    <section className={s.honesty}>
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} />
      ) : (
        <p className={s.honestyText}>{q.data.caveats.join("  ·  ")}</p>
      )}
    </section>
  );
}
