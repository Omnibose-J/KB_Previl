import type { ReactNode } from "react";
import type { Confidence, Resolutions } from "../api/types";
import ui from "../styles/ui.module.css";

// Uncertainty is a designed element, not an omission (ui-spec §0 원칙 6, §4).
// These components make it impossible to render a missing value as 0, or a
// coarse value without its unit — the rule lives in the component, not in each
// screen's discipline.
//
// The unit text comes from the payload's `resolutions` map, not a table here:
// lane B knows the real source resolution per field (격자 100m / 이웃 300m /
// 행정동 / 상권 반경 151m), and a second copy on the client would drift.

/** Renders NULL. The hatch swatch is in ui.module.css (.missing::before). */
export function Missing({ reason }: { reason?: string }) {
  return (
    <span className={ui.missing}>
      정보 없음
      {reason ? <span className={ui.caption}>{reason}</span> : null}
    </span>
  );
}

/**
 * Value + its source-resolution caption. Values coarser than the 100m grid are
 * identical across every cell in the same unit, and saying so is non-negotiable
 * (lane C brief item 4).
 */
export function Value({
  value,
  resolutions,
  field,
  missingReason,
}: {
  value: ReactNode | null;
  /** the payload's resolutions map */
  resolutions?: Resolutions;
  /** key into that map, e.g. "areaSurvival" or "demand.dayPopulation" */
  field?: string;
  missingReason?: string;
}) {
  if (value === null || value === undefined) return <Missing reason={missingReason} />;
  const unit = resolutions && field ? resolutions[field] : undefined;
  return (
    <>
      {value}
      {unit ? <span className={ui.caption}> {unit}</span> : null}
    </>
  );
}

/**
 * full = no badge (the default state earns no ink). partial = the grid sits
 * outside every trade area, so sales/footfall axes are absent (ui-spec §4).
 */
export function ConfidenceBadge({
  confidence,
  missingAxes,
}: {
  confidence: Confidence;
  missingAxes?: string[];
}) {
  if (confidence === "full") return null;
  const axes = missingAxes?.length ? missingAxes.join(" · ") : "매출 · 유동";
  return (
    <span className={ui.pillNeutral} title={`빈 축: ${axes}`}>
      상권 밖 — {axes} 정보 없음
    </span>
  );
}
