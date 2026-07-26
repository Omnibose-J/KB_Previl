import type { GridDetail, StationAnchor } from "../api/types";
import { int, meters, pct1, signedCount, survivalSentence } from "../lib/format";
import GradeBadge from "./GradeBadge";
import { ConfidenceBadge, Missing } from "./values";
import s from "./CandidateCard.module.css";
import ui from "../styles/ui.module.css";

/** Station name plus distance when measured; the name alone otherwise. */
export function stationAnchor(a: StationAnchor): string {
  return a.distanceM === null ? a.name : `${a.name} ${meters(a.distanceM)}`;
}

// 후보 카드 — ui-spec §3-S3.
// Deleted from the mockup card and NOT to be reintroduced: 예상 월매출 (the
// model does not predict revenue), 손익분기 alone (identical across grades, so
// it misleads), 적합도 92점 (pseudo-precision duplicating the grade), 매물 N건
// (we have no listings). One status pill per card, maximum.

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
      className={selected ? `${s.card} ${ui.cardAccent}` : s.card}
      onMouseEnter={() => onHover(cell.gridId)}
      onMouseLeave={() => onHover(null)}
      onClick={onSelect}
    >
      <div className={s.top}>
        <span className={s.rank}>{rank}</span>
        <div className={s.title}>
          {/* 행정동 + 위치 앵커. "블록" is banned — it claims a resolution we
              do not have (§3-S3). No bearing: B does not compute one, and
              inventing "남측" would be a direction we never measured. */}
          <h3 className={s.name}>{cell.admDong ?? "행정동 미상"}</h3>
          <p className={s.anchor}>
            {cell.district ?? "자치구 미상"}
            {cell.nearestStation ? ` · ${stationAnchor(cell.nearestStation)}` : ""}
          </p>
        </div>
        <Signal cell={cell} />
      </div>

      <p className={s.sentence}>{survivalSentence(cell.observedSurvival)}</p>

      <div className={ui.tileRow}>
        <div className={ui.tile}>
          <span className={ui.tileLabel}>입지 등급</span>
          <GradeBadge grade={cell.grade} />
        </div>
        <div className={ui.tile}>
          <span className={ui.tileLabel}>이 등급의 실측 3년 생존율</span>
          <span className={ui.tileValue}>{pct1(cell.observedSurvival)}</span>
        </div>
      </div>

      <div className={ui.dataChips}>
        <Chip label="영업 점포" value={cell.competition.shopsHere} render={int} />
        <Chip
          label="최근 3년 개업"
          value={cell.competition.openings36m}
          render={signedCount}
          fallbackLabel="누적 개업"
          fallbackValue={cell.competition.openingsTotal}
        />
        <NeighbourChip cell={cell} />
      </div>

      <div className={s.foot}>
        <ConfidenceBadge confidence={cell.confidence} missingAxes={cell.missingAxes} />
        <button
          className={ui.btnGhost}
          onClick={(e) => {
            e.stopPropagation();
            onOpen();
          }}
        >
          자세히 보기 →
        </button>
      </div>
    </li>
  );
}

/**
 * 검증된 자리 / 과열 신호. The verdict is computed by lane A and shipped in the
 * payload — the front end must not derive it from thresholds of its own
 * (§3-S3). "상승 초입" is banned: we never predicted a rise.
 */
function Signal({ cell }: { cell: GridDetail }) {
  if (cell.signal === "verified") return <span className={ui.pillPositive}>검증된 자리</span>;
  if (cell.signal === "overheated") return <span className={ui.pillCaution}>과열 신호</span>;
  return null;
}

function Chip({
  label,
  value,
  render,
  fallbackLabel,
  fallbackValue,
}: {
  label: string;
  value: number | null;
  render: (v: number) => string;
  /** Used when the primary metric has not been produced yet (openings_36m is a
   *  lane A backlog item). This is a DIFFERENT, honestly-labelled measure —
   *  not the same number invented (ui-spec §1). */
  fallbackLabel?: string;
  fallbackValue?: number | null;
}) {
  if (value !== null) {
    return (
      <span className={ui.dataChip}>
        {label} <strong>{render(value)}</strong>
      </span>
    );
  }
  if (fallbackLabel && fallbackValue !== null && fallbackValue !== undefined) {
    return (
      <span className={ui.dataChip}>
        {fallbackLabel} <strong>{int(fallbackValue)}</strong>
      </span>
    );
  }
  return (
    <span className={ui.dataChip}>
      {label} <Missing />
    </span>
  );
}

/** 이웃 생존율 carries its sample size: a rate over 3 shops is not a finding. */
function NeighbourChip({ cell }: { cell: GridDetail }) {
  const { rate, sample } = cell.areaSurvival;
  if (rate === null) {
    return (
      <span className={ui.dataChip}>
        이웃 생존율 <Missing reason="표본 부족" />
      </span>
    );
  }
  return (
    <span className={ui.dataChip}>
      이웃 생존율 <strong>{pct1(rate)}</strong>
      <span className={ui.caption}>
        {sample !== null ? ` 표본 ${int(sample)}` : " 표본 미상"}
        {cell.resolutions.areaSurvival ? ` · ${cell.resolutions.areaSurvival}` : ""}
      </span>
    </span>
  );
}
