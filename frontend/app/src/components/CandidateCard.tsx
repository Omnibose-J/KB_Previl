import type { GridDetail } from "../api/types";
import { int, meters, pct1, stationAnchor } from "../lib/format";
import s from "./CandidateCard.module.css";

// 후보 카드, figma-snapshot S3 card layout (rank box · title · pills · metric
// strip · evidence line). The mockup's four metrics are swapped for what we
// actually stand behind (ui-spec §3-S3): 예상 월매출→실측 생존율, 적합도
// 92점→등급, 매물 N건→위치 앵커. Card title is 행정동+anchor — "블록" is a
// resolution claim we cannot make. No bearing: B does not compute one.

export default function CandidateCard({
  rank,
  cell,
  selected,
  onHover,
  onSelect,
  onOpen,
}: {
  rank: number;
  cell: GridDetail;
  selected: boolean;
  onHover: (id: string | null) => void;
  onSelect: () => void;
  onOpen: () => void;
}) {
  return (
    <li
      className={selected ? s.cardOn : s.card}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onMouseEnter={() => onHover(cell.gridId)}
      onMouseLeave={() => onHover(null)}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className={s.top}>
        <div className={s.ti}>
          <span className={rank === 1 ? s.rankTop : s.rank}>{rank}</span>
          <div className={s.nm}>
            <h3 className={s.name}>{cell.admDong ?? "행정동 미상"}</h3>
            <p className={s.anchor}>
              {cell.district ?? "자치구 미상"}
              {cell.nearestStation ? ` · ${stationAnchor(cell.nearestStation)}` : ""}
            </p>
            <div className={s.pills}>
              {cell.confidence === "partial" ? <span className={s.pillGray}>상권 밖</span> : null}
              <span className={s.gradePill}>{cell.grade}등급</span>
            </div>
          </div>
        </div>
        {/* The card's ONE big number: this grid's own neighbourhood record —
            it varies card to card, unlike the grade observed rate (UX critique:
            two competing percents; the grade rate moved to the micro stats). */}
        <div className={s.bigStat}>
          {cell.areaSurvival.rate !== null ? (
            <>
              <strong>{pct1(cell.areaSurvival.rate)}</strong>
              <span>
                이 자리 주변 3년 생존율
                {cell.areaSurvival.sample !== null ? ` (${int(cell.areaSurvival.sample)}곳 기준)` : ""}
              </span>
            </>
          ) : (
            <span className={s.bigStatMissing}>주변 생존 기록 없음</span>
          )}
        </div>
      </div>

      <div className={s.micro}>
        {/* Every recommended cell is top-graded, so the per-grade rate is the
            same number on all 24 cards — it read as hardcoded (owner report
            2026-07-27). Per-cell counts vary; the grade rate lives in S4. */}
        {/* 첫 칸만 선택한 업태, 나머지 둘은 업태 무관 음식점 누계다. 라벨에
            그대로 적는다 — 예전엔 셋 다 «가게»여서 어느 것이 업태별인지 알 수
            없었고, 실제로 첫 칸은 업태와 무관한 전체 음식점 수였다. */}
        <Micro
          label={`${cell.uptae} 가게`}
          value={
            cell.competition.sameUptaeHere !== null
              ? `${int(cell.competition.sameUptaeHere)}곳`
              : null
          }
        />
        <Micro
          label="지금까지 연 음식점"
          value={cell.competition.openingsTotal !== null ? `${int(cell.competition.openingsTotal)}곳` : null}
        />
        <Micro
          label="지금까지 닫은 음식점"
          value={cell.competition.closuresTotal !== null ? `${int(cell.competition.closuresTotal)}곳` : null}
        />
        <Micro
          label="역까지"
          value={cell.nearestStation?.distanceM != null ? meters(cell.nearestStation.distanceM) : null}
        />
        <button
          className={s.open}
          onClick={(e) => {
            e.stopPropagation();
            onOpen();
          }}
        >
          상세 리포트 →
        </button>
      </div>

      <ConceptLine cell={cell} />
    </li>
  );
}

// 주변에 많은 가게 종류 한 줄. 후보 사이 차이를 읽히게 하는 것이 목적이라
// 상위 3종만 낸다 — 전체 구성은 S4 카드가 맡는다. 추천 순서에는 관여하지
// 않는다(정렬은 score 그대로).
const CONCEPT_TOP = 3;

function ConceptLine({ cell }: { cell: GridDetail }) {
  const mix = cell.conceptMix;
  if (!mix?.available || mix.items.length === 0) return null;
  return (
    <p className={s.concepts}>
      <span className={s.conceptsLabel}>주변에 많은 가게</span>
      {mix.items.slice(0, CONCEPT_TOP).map((item) => (
        <span key={item.concept} className={s.conceptChip}>
          {item.concept} {int(item.shops)}
        </span>
      ))}
    </p>
  );
}

function Micro({ label, value }: { label: string; value: string | null }) {
  return (
    <div className={s.mi}>
      <span>{label}</span>
      <strong>{value ?? "정보 없음"}</strong>
    </div>
  );
}

/**
 * 검증된 자리 / 과열 신호 배지는 뺐다. 「최근 개업 급증 = 위험」을 확정
 * 홀드아웃(2023 코호트 n=7,915)에서 재보니 급증 상위 10% 의 3년 생존율이
 * 60.4% [56.8, 63.8] 로 나머지 57.8% [56.5, 59.0] 보다 «높았고» CI 도 겹쳤다
 * — 방향이 반대이고 구분도 안 된다(docs/model-findings.md §22).
 *
 * 다른 정의로 검정해 CI 가 0 을 벗어나면 그때 되살리면 된다. 렌더될 수 없는
 * 자리를 남겨두면 다음 사람이 「레인 A 대기」로 읽고 같은 일을 반복한다.
 */
