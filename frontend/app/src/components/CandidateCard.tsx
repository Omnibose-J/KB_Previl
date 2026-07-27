import type { GridDetail, StationAnchor } from "../api/types";
import { int, meters, pct0, pct1, signedCount } from "../lib/format";
import s from "./CandidateCard.module.css";

/** Station name plus distance when measured; the name alone otherwise. */
export function stationAnchor(a: StationAnchor): string {
  return a.distanceM === null ? a.name : `${a.name} ${meters(a.distanceM)}`;
}

// 후보 카드, figma-snapshot S3 card layout (rank box · title · pills · metric
// strip · evidence line). The mockup's four metrics are swapped for what we
// actually stand behind (ui-spec §3-S3): 예상 월매출→실측 생존율, 적합도
// 92점→등급, 매물 N건→위치 앵커. Card title is 행정동+anchor — "블록" is a
// resolution claim we cannot make. No bearing: B does not compute one.

export default function CandidateCard({
  rank,
  cell,
  rentMonthly,
  selected,
  onHover,
  onSelect,
  onOpen,
}: {
  rank: number;
  cell: GridDetail;
  rentMonthly: number | null;
  selected: boolean;
  onHover: (id: string | null) => void;
  onSelect: () => void;
  onOpen: () => void;
}) {
  return (
    <li
      className={selected ? s.cardOn : s.card}
      onMouseEnter={() => onHover(cell.gridId)}
      onMouseLeave={() => onHover(null)}
      onClick={onSelect}
    >
      <div className={s.top}>
        <div className={s.ti}>
          <span className={rank === 1 ? s.rankTop : s.rank}>{rank}</span>
          <div className={s.nm}>
            <h3 className={s.name}>{cell.admDong ?? "행정동 미상"}</h3>
            <p className={s.anchor}>
              {cell.district ?? "자치구 미상"}
              {cell.nearestStation ? ` · ${stationAnchor(cell.nearestStation)}` : ""}
              {" · 100m 격자"}
            </p>
          </div>
        </div>
        <div className={s.pills}>
          <Signal cell={cell} />
          {/* "상위 n%" is banned — decile boundaries are holdout-absolute
              (serving-design §3). The honest companion number is the observed
              survival of this grade. */}
          <span className={s.gradePill}>
            {cell.grade}등급 · 실측 {pct0(cell.observedSurvival)}
          </span>
        </div>
      </div>

      <div className={s.metrics}>
        <div className={s.m}>
          <span>입지 등급</span>
          <strong>{cell.grade}등급</strong>
        </div>
        <div className={s.m}>
          <span>실측 3년 생존율</span>
          <strong>{pct0(cell.observedSurvival)}</strong>
          <em>같은 등급 자리 실측</em>
        </div>
        <div className={s.m}>
          <span>3년 기대손익</span>
          {rentMonthly === null ? (
            <>
              <strong className={s.mMuted}>미계산</strong>
              <em>임대료 입력 시 계산</em>
            </>
          ) : (
            <>
              <strong className={s.mMuted}>상세에서 확인</strong>
              <em>월 {int(rentMonthly)}만 기준</em>
            </>
          )}
        </div>
        <div className={s.m}>
          <span>신뢰도</span>
          <strong className={cell.confidence === "partial" ? s.mMuted : undefined}>
            {cell.confidence === "partial" ? "상권 밖" : "충분"}
          </strong>
          {cell.confidence === "partial" ? <em>매출·유동 정보 없음</em> : null}
        </div>
      </div>

      <p className={s.evidence}>
        <strong>근거</strong>
        {"  "}
        {evidenceLine(cell)}
        <button
          className={s.open}
          onClick={(e) => {
            e.stopPropagation();
            onOpen();
          }}
        >
          상세 리포트 →
        </button>
      </p>
    </li>
  );
}

/** Real-data evidence chips joined like the mockup's 근거 line — every value
 *  from the payload, NULL stated as such (never 0). */
function evidenceLine(cell: GridDetail): string {
  const parts: string[] = [];
  if (cell.competition.shopsHere !== null) parts.push(`영업 점포 ${int(cell.competition.shopsHere)}`);
  if (cell.competition.openings36m !== null)
    parts.push(`최근 3년 개업 ${signedCount(cell.competition.openings36m)}`);
  else if (cell.competition.openingsTotal !== null)
    parts.push(`누적 개업 ${int(cell.competition.openingsTotal)}`);
  if (cell.areaSurvival.rate !== null)
    parts.push(
      `이웃 생존율 ${pct1(cell.areaSurvival.rate)}${
        cell.areaSurvival.sample !== null ? ` (표본 ${int(cell.areaSurvival.sample)})` : ""
      }`,
    );
  if (cell.nearestStation?.distanceM != null) parts.push(`역까지 ${meters(cell.nearestStation.distanceM)}`);
  return parts.length > 0 ? parts.join(" · ") : "표시할 실측 근거 없음";
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
