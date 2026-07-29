import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Map as MlMap,
  Marker,
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

/** Quantise the viewport so a 2px pan does not refetch (the API caps cells).
 *  Outward only — floor west/south, ceil east/north. Symmetric rounding could
 *  SHRINK the bbox by up to ~0.001° per edge (~one 100m cell), silently
 *  dropping cells at the viewport border. */
const quantise = ([w, s, e, n]: Bbox): Bbox => [
  Math.floor(w * 500) / 500,
  Math.floor(s * 500) / 500,
  Math.ceil(e * 500) / 500,
  Math.ceil(n * 500) / 500,
];

/** Cells only exist above the server's viewport cap, so the map must ARRIVE
 *  zoomed in on a real candidate. Opening on all of Seoul renders an empty map
 *  (413) and reads as "no data here" — the wrong claim entirely. */
const FOCUS_ZOOM = 15;

/** Dark rank pin (figma S3 "Pin/…"): rank circle + 행정동 label. */
export interface MapPin {
  id: string;
  rank: number;
  label: string;
  center: Point;
}

export default function GridMap({
  uptae,
  focus,
  candidateIds,
  pins = [],
  selectedId,
  hoveredId,
  onSelect,
  onOpenDetail,
}: {
  uptae: string;
  focus: Point | null;
  /** grid ids that made the ranked list — outlined dark on the yellow ramp */
  candidateIds: string[];
  pins?: MapPin[];
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (cell: GridCell) => void;
  /** diagnosis entry: any tapped cell can open its full report */
  onOpenDetail?: (cell: GridCell) => void;
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
      // 셀 중심에 깔리는 번짐층. 격자가 체스판처럼 각져 보이는 것을 눅인다 —
      // 같은 등급끼리는 서로 번져 하나의 면으로 읽히고, 바깥으로는 색이 서서히
      // 빠진다. fill 레이어에는 blur 가 없어서 circle-blur 로 만든다.
      //
      // 이 층은 «장식»이고 판정 근거가 아니다. 그래서 아래에 깔고 위에 원래
      // fill 을 그대로 얹는다 — 어느 100m 칸이 실제로 채점됐는지는 여전히
      // fill 의 또렷한 경계가 말한다. 번짐만 남기면 점수가 없는 칸까지 색이
      // 번져 «여기도 평가됐다»로 읽힌다.
      //
      // circle-blur 1 은 «반지름 안에서» 중심 불투명 -> 가장자리 0 으로 떨어진다.
      // 바깥으로 번지는 것이 아니다. 그래서 반지름을 셀 반폭에 맞추면 번짐이
      // 통째로 fill 밑에 깔려 아무것도 안 보인다(처음에 그렇게 만들어 확인했다).
      // 셀 반폭의 1.8배로 잡아야 1.0~1.8 구간이 셀 밖으로 나와 후광이 된다.
      //
      // 반폭 픽셀값: 위도 37.5 에서 1픽셀 = 156543·cos(37.5)/2^z 미터이므로
      // 100m 의 절반은 z13 에서 3.3px, z17 에서 53px 이고 줌 1당 정확히 두 배다
      // — exponential base 2 가 그 관계 그대로다. 여기에 1.8 을 곱한다.
      // circle 레이어는 Point 만 그린다 — 폴리곤 소스로는 아무것도 안 나온다.
      // 그래서 셀 중심점을 별도 소스로 둔다(B 가 center 를 이미 준다).
      m.addSource("grid-centres", { type: "geojson", data: emptyFc() });
      m.addLayer({
        id: "grid-glow",
        type: "heatmap",
        source: "grid-centres",
        paint: {
          // 등급을 무게로 준다. 1등급이 1.0, 10등급이 0.1 — 밀도가 아니라
          // «등급의 면»을 그리는 것이 목적이다. 셀 간격이 100m 로 일정해서
          // 밀도항은 거의 상수이고, 결과는 등급을 부드럽게 이어붙인 면이 된다.
          "heatmap-weight": ["/", ["-", 11, ["get", "grade"]], 10],
          // 셀 간격(100m)의 약 2.5배. 화면상 간격은 z13 에서 6.6px, z17 에서
          // 105.6px 이고, 커널이 그보다 작으면 칸마다 점이 찍혀 물방울무늬가
          // 된다(9px 로 만들어 확인했다). 커널끼리 충분히 겹쳐야 면이 된다.
          "heatmap-radius": [
            "interpolate",
            ["exponential", 2],
            ["zoom"],
            13, 17,
            17, 270,
          ],
          "heatmap-intensity": 1,
          "heatmap-opacity": 0.85,
          // 0 은 완전 투명이어야 한다 — 점수가 없는 곳까지 색이 깔리면
          // «여기도 평가됐다»로 읽힌다.
          "heatmap-color": [
            "interpolate",
            ["linear"],
            ["heatmap-density"],
            0, "rgba(0,0,0,0)",
            0.15, "rgba(255,236,190,0.55)",
            0.4, "rgba(255,205,90,0.75)",
            0.7, "rgba(247,163,26,0.85)",
            1, "rgba(226,121,0,0.92)",
          ],
        },
      });
      m.addLayer({
        id: "grid-fill",
        type: "fill",
        source: "grids",
        // Ramp colors carry their own alpha; the extra fill-opacity keeps
        // roads/labels legible under dense grade-1 areas (UX critique).
        // 아래 heatmap 이 면을 만들고, fill 은 «어느 100m 칸이 실제로 채점됐나»
        // 를 표시하는 얇은 층으로 남는다. 예전 0.85 를 유지하면 heatmap 이
        // 통째로 가려져 다시 모자이크가 된다.
        paint: { "fill-color": ["get", "color"], "fill-opacity": 0.45 },
      });
      // Ranked candidates get a dark outline: the ramp itself is now brand
      // yellow (figma heatmap), so yellow outlines would vanish into it.
      m.addLayer({
        id: "grid-top",
        type: "line",
        source: "grids",
        filter: ["in", ["get", "gridId"], ["literal", []]],
        paint: { "line-color": "#141414", "line-width": 1.6 },
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
      // No syncBbox() here: the map opens on all of Seoul (zoom 12), where a
      // fetch is a guaranteed 413 — a wasted request plus a false "too many
      // cells" flash. The first fetch fires on moveend, i.e. after the flyTo
      // to the top candidate (or the user's own first pan).
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
    const centres = map.current?.getSource("grid-centres") as GeoJSONSource | undefined;
    if (!src || !centres) return;
    const cells = q.data?.items;
    src.setData(cells ? toFc(cells) : emptyFc());
    centres.setData(cells ? toCentreFc(cells) : emptyFc());
  }, [q.data, ready]);

  useEffect(() => {
    const m = map.current;
    if (!m?.getLayer("grid-active")) return;
    m.setFilter("grid-active", ["==", ["get", "gridId"], hoveredId ?? selectedId ?? ""]);
    // `ready` matters: cached selection can land before the style loads.
  }, [hoveredId, selectedId, ready]);

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

  // Dark rank pins for the top candidates (figma S3). DOM markers so the pill
  // styling matches the mockup exactly.
  const markers = useRef<Marker[]>([]);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    markers.current.forEach((mk) => mk.remove());
    markers.current = pins.map((p) => {
      const el = document.createElement("div");
      el.className = s.pin;
      el.innerHTML = `<i>${p.rank}</i><span></span>`;
      (el.querySelector("span") as HTMLSpanElement).textContent = p.label;
      return new Marker({ element: el, anchor: "bottom", offset: [0, -6] })
        .setLngLat(p.center)
        .addTo(m);
    });
    return () => {
      markers.current.forEach((mk) => mk.remove());
      markers.current = [];
    };
  }, [pins, ready]);

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
        <Bubble cell={q.data.items.find((c) => c.gridId === selectedId)} onOpen={onOpenDetail} />
      ) : null}
    </div>
  );
}

/** 값 1개 + 방향 1개 + 진입 액션 1개. Denser than that and the map stops being
 *  readable — the information density borrowed from 호갱노노 / KB부동산. */
function Bubble({ cell, onOpen }: { cell?: GridCell; onOpen?: (cell: GridCell) => void }) {
  if (!cell) return null;
  return (
    <div className={s.bubble}>
      <strong>{gradeLabel(cell.grade)}</strong>
      <span>{survivalSentence(cell.observedSurvival)}</span>
      {onOpen ? (
        <button className={s.bubbleOpen} onClick={() => onOpen(cell)}>
          이 자리 상세 리포트 →
        </button>
      ) : null}
    </div>
  );
}

/** Figma floating legend: 낮음 → five swatches → 높음. Swatches sample the
 *  10-step ramp at the labelled stops (§3-S3: 10 labels are unreadable). */
function Legend() {
  return (
    <div className={s.legend}>
      <span>등급 낮음</span>
      {[...LEGEND_STEPS].reverse().map((g: Grade) => (
        <i key={g} className={s.swatch} style={{ background: `var(--color-heatmap-${g})` }} />
      ))}
      <span>높음</span>
      <span className={s.legendNote}>1등급이 가장 좋은 자리</span>
    </div>
  );
}

// --- geojson ---------------------------------------------------------------

const emptyFc = (): FeatureCollection => ({ type: "FeatureCollection", features: [] });

/** 등급 -> 램프 색. One style lookup per grade, not one per cell. */
const RAMP = new Map<number, string>();
function colorOfGrade(g: number): string {
  let c = RAMP.get(g);
  if (!c) {
    c = getComputedStyle(document.documentElement)
      .getPropertyValue(`--color-heatmap-${g}`)
      .trim();
    RAMP.set(g, c);
  }
  return c;
}

function toFc(cells: GridCell[]): FeatureCollection {
  const colorOf = colorOfGrade;
  return {
    type: "FeatureCollection",
    features: cells.map((c) => ({
      type: "Feature" as const,
      geometry: { type: "Polygon" as const, coordinates: [closeRing(c.polygon)] },
      properties: {
        gridId: c.gridId,
        grade: c.grade,
        // Read straight off the token ramp so map and badges never drift.
        color: colorOf(c.grade),
        cell: JSON.stringify(c),
      },
    })),
  };
}

/** heatmap 용 셀 중심점. 등급만 있으면 되므로 cell 원본은 싣지 않는다 — 같은
 *  데이터를 두 소스에 복사하면 클릭이 어느 쪽을 집었는지 모호해진다.
 *  클릭·호버는 전부 grid-fill 이 받는다. */
function toCentreFc(cells: GridCell[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: cells.map((c) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: c.center },
      properties: { grade: c.grade },
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
