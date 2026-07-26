import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Map as MlMap,
  NavigationControl,
  type GeoJSONSource,
  type LngLatBoundsLike,
  type MapLayerMouseEvent,
  type StyleSpecification,
} from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
import { ApiError, api } from "../api/client";
import type { GridCell, Grade, Point } from "../api/types";
import { LEGEND_STEPS, gradeLabel } from "../lib/grade";
import { survivalSentence } from "../lib/format";
import { ErrorState, Loading } from "./states";
import s from "./GridMap.module.css";

// Map-first navigation (ui-spec §0 원칙 4). MapLibre + OSM raster, because
// KAKAO_JAVASCRIPT_KEY was never issued — the spec's declared fallback (§1).
//
// Cells are drawn as real 100m polygons, never points or a continuous heatmap:
// a blurred gradient would visually claim a resolution we do not have, and a
// continuous alpha ramp implies a score when the decile is all we validated.

const SEOUL_CENTER: [number, number] = [126.978, 37.5665];
const SEOUL_MAX_BOUNDS: LngLatBoundsLike = [
  [126.73, 37.4],
  [127.27, 37.71],
];

/** Grey basemap so the data layer carries the colour — KB부동산 does the same. */
const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [
    {
      id: "osm",
      type: "raster",
      source: "osm",
      paint: { "raster-saturation": -0.9, "raster-opacity": 0.55 },
    },
  ],
};

type Bbox = [number, number, number, number];

/** Quantise the viewport so a 2px pan does not refetch (the API caps cells). */
const quantise = (b: Bbox): Bbox => b.map((v) => Math.round(v * 500) / 500) as Bbox;

/** Cells only exist above the server's viewport cap, so the map must ARRIVE
 *  zoomed in on a real candidate. Opening on all of Seoul renders an empty map
 *  (413) and reads as "no data here" — the wrong claim entirely. */
const FOCUS_ZOOM = 15;

export default function GridMap({
  uptae,
  focus,
  candidateIds,
  selectedId,
  hoveredId,
  onSelect,
}: {
  uptae: string;
  focus: Point | null;
  /** grid ids that made the ranked list — the only cells allowed brand yellow */
  candidateIds: string[];
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (cell: GridCell) => void;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const [bbox, setBbox] = useState<Bbox | null>(null);
  /* The style loads asynchronously, so the source does not exist yet when the
     component mounts. Cached query data can therefore arrive BEFORE the map is
     ready; without this flag that data is dropped and the map stays empty on
     every re-entry. */
  const [ready, setReady] = useState(false);

  const q = useQuery({
    queryKey: ["grids", uptae, bbox],
    queryFn: () => api.grids(uptae, bbox!),
    enabled: bbox !== null,
  });

  // --- map lifecycle -------------------------------------------------------
  useEffect(() => {
    if (!holder.current) return;
    const m = new MlMap({
      container: holder.current,
      style: BASE_STYLE,
      center: SEOUL_CENTER,
      zoom: 12,
      maxBounds: SEOUL_MAX_BOUNDS,
      attributionControl: { compact: true },
    });
    m.addControl(new NavigationControl({ showCompass: false }), "bottom-right");

    const syncBbox = () => {
      const b = m.getBounds();
      setBbox(quantise([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]));
    };

    m.on("load", () => {
      m.addSource("grids", { type: "geojson", data: emptyFc() });
      m.addLayer({
        id: "grid-fill",
        type: "fill",
        source: "grids",
        paint: { "fill-color": ["get", "color"], "fill-opacity": 0.72 },
      });
      m.addLayer({
        id: "grid-line",
        type: "line",
        source: "grids",
        paint: { "line-color": "#FFFFFF", "line-width": 0.4, "line-opacity": 0.5 },
      });
      // Brand yellow marks the ranked candidates only. Outlining every grade-1
      // cell looked right in the spec but not on screen: in a dense district
      // most cells are grade 1, so the map turned into a yellow grid and the
      // accent stopped meaning anything (§0 원칙 5 outranks its own example).
      m.addLayer({
        id: "grid-top",
        type: "line",
        source: "grids",
        filter: ["in", ["get", "gridId"], ["literal", []]],
        paint: { "line-color": "#FFBC00", "line-width": 2.5 },
      });
      // Hover/selection echo from the list (Zillow-style two-way sync).
      m.addLayer({
        id: "grid-active",
        type: "line",
        source: "grids",
        filter: ["==", ["get", "gridId"], ""],
        paint: { "line-color": "#0E0E0E", "line-width": 2.5 },
      });
      m.on("click", "grid-fill", (e: MapLayerMouseEvent) => {
        const raw = e.features?.[0]?.properties?.cell;
        if (typeof raw === "string") onSelect(JSON.parse(raw) as GridCell);
      });
      m.on("mouseenter", "grid-fill", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "grid-fill", () => (m.getCanvas().style.cursor = ""));
      syncBbox();
      setReady(true);
    });
    m.on("moveend", syncBbox);

    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      setReady(false);
    };
    // onSelect is stable enough for a demo-scale screen; re-creating the map on
    // every render would destroy the user's viewport.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- data ---------------------------------------------------------------
  useEffect(() => {
    const src = map.current?.getSource("grids") as GeoJSONSource | undefined;
    if (!src) return;
    src.setData(q.data ? toFc(q.data.items) : emptyFc());
  }, [q.data, ready]);

  useEffect(() => {
    const m = map.current;
    if (!m?.getLayer("grid-active")) return;
    m.setFilter("grid-active", ["==", ["get", "gridId"], hoveredId ?? selectedId ?? ""]);
  }, [hoveredId, selectedId]);

  useEffect(() => {
    const m = map.current;
    if (!m?.getLayer("grid-top")) return;
    m.setFilter("grid-top", ["in", ["get", "gridId"], ["literal", candidateIds]]);
  }, [candidateIds, ready]);

  useEffect(() => {
    const m = map.current;
    if (!m || !focus) return;
    m.flyTo({ center: focus, zoom: Math.max(m.getZoom(), FOCUS_ZOOM), speed: 1.6 });
  }, [focus]);

  return (
    <div className={s.wrap}>
      <div ref={holder} className={s.canvas} />
      <div className={s.overlay}>
        {q.isPending && bbox ? <Loading label="격자 불러오는 중…" /> : null}
        {/* 413 is not a failure to explain away: the server refuses to thin the
            cells because a sampled map would misrepresent coverage (§B 계약). */}
        {q.error instanceof ApiError && q.error.status === 413 ? (
          <p className={s.zoomHint}>격자가 너무 많습니다 — 지도를 확대해주세요.</p>
        ) : q.isError ? (
          <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} />
        ) : null}
      </div>
      <Legend />
      {selectedId && q.data ? (
        <Bubble cell={q.data.items.find((c) => c.gridId === selectedId)} />
      ) : null}
    </div>
  );
}

/** 값 1개 + 방향 1개. Denser than that and the map stops being readable — the
 *  information density borrowed from 호갱노노 / KB부동산 markers. */
function Bubble({ cell }: { cell?: GridCell }) {
  if (!cell) return null;
  return (
    <div className={s.bubble}>
      <strong>{gradeLabel(cell.grade)}</strong>
      <span>{survivalSentence(cell.observedSurvival)}</span>
    </div>
  );
}

/** Five labelled stops out of ten — labelling all ten is unreadable (§3-S3). */
function Legend() {
  return (
    <div className={s.legend}>
      <span className={s.legendTitle}>입지 등급</span>
      <div className={s.ramp}>
        {(Array.from({ length: 10 }, (_, i) => i + 1) as Grade[]).map((g) => (
          <i key={g} style={{ background: `var(--color-heatmap-${g})` }} />
        ))}
      </div>
      <div className={s.legendScale}>
        {LEGEND_STEPS.map((g) => (
          <span key={g}>{g}</span>
        ))}
      </div>
      <span className={s.legendNote}>1등급이 가장 좋은 자리입니다</span>
    </div>
  );
}

// --- geojson ---------------------------------------------------------------

const emptyFc = (): FeatureCollection => ({ type: "FeatureCollection", features: [] });

function toFc(cells: GridCell[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: cells.map((c) => ({
      type: "Feature" as const,
      geometry: { type: "Polygon" as const, coordinates: [closeRing(c.polygon)] },
      properties: {
        gridId: c.gridId,
        grade: c.grade,
        // Read straight off the token ramp so map and badges never drift.
        color: getComputedStyle(document.documentElement)
          .getPropertyValue(`--color-heatmap-${c.grade}`)
          .trim(),
        cell: JSON.stringify(c),
      },
    })),
  };
}

/** GeoJSON rings must be closed; B sends four corners. */
function closeRing(ring: [number, number][]): [number, number][] {
  if (ring.length === 0) return ring;
  const [first] = ring;
  const last = ring[ring.length - 1];
  return first[0] === last[0] && first[1] === last[1] ? ring : [...ring, first];
}
