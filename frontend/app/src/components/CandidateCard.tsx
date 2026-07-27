import type { GridDetail } from "../api/types";
import { int, meters, pct0, pct1, stationAnchor } from "../lib/format";
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
              <Signal cell={cell} />
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
                주변 가게 3년 생존율
                {cell.areaSurvival.sample !== null ? ` (${int(cell.areaSurvival.sample)}곳 기준)` : ""}
              </span>
            </>
          ) : (
            <span className={s.bigStatMissing}>주변 생존 기록 없음</span>
          )}
        </div>
      </div>

      <div className={s.micro}>
        <Micro label="같은 등급 생존율" value={pct0(cell.observedSurvival)} />
        <Micro
          label="영업 중인 가게"
          value={cell.competition.shopsHere !== null ? `${int(cell.competition.shopsHere)}곳` : null}
        />
        <Micro
          label="지금까지 연 가게"
          value={cell.competition.openingsTotal !== null ? `${int(cell.competition.openingsTotal)}곳` : null}
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
    </li>
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
 * 검증된 자리 / 과열 신호. The verdict is computed by lane A and shipped in the
 * payload — the front end must not derive it from thresholds of its own
 * (§3-S3). "상승 초입" is banned: we never predicted a rise.
 */
function Signal({ cell }: { cell: GridDetail }) {
  if (cell.signal === "verified") return <span className={s.pillGreen}>검증된 자리</span>;
  if (cell.signal === "overheated") return <span className={s.pillOrange}>과열 신호</span>;
  return null;
}
