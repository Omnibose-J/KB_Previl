import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Map as MlMap,
  Marker,
  NavigationControl,
  type CanvasSource,
  type GeoJSONSource,
  type LngLatBoundsLike,
  type MapLayerMouseEvent,
  type StyleSpecification,
} from "maplibre-gl";
import { emptyFc, makeColorOf, paintField, toFc } from "../lib/gridGeo";

/** 지도 소스가 물고 있는 캔버스 하나. 갱신 때마다 여기에 다시 그린다. */
let sharedField: HTMLCanvasElement | null = null;
function fieldCanvas() {
  if (!sharedField) {
    sharedField = document.createElement("canvas");
    sharedField.width = 1;
    sharedField.height = 1;
  }
  return sharedField;
}

/**
 * 등급 면 그림을 지도에 올리고 갱신한다.
 *
 * 소스를 «데이터가 생긴 뒤에» 붙인다. 빈 좌표(`0,0` 네 개)로 미리 만들어 두면
 * 타일 좌표가 Infinity 가 되면서 지도 전체가 죽는다 — 실제로 그렇게 깨졌다.
 */
function ensureField(m: MlMap, cells: GridCell[]) {
  const target = fieldCanvas();
  const ctx = target.getContext("2d");
  if (!ctx) return;
  const source = m.getSource("grid-field") as CanvasSource | undefined;
  const painted = cells.length ? paintField(cells, makeColorOf()) : null;
  if (!painted) {
    // 칸이 없으면 비운다. 낡은 그림이 남으면 다른 업종의 면이 그대로 보인다.
    ctx.clearRect(0, 0, target.width, target.height);
    source?.setCoordinates(source.coordinates);   // 캔버스를 다시 읽게 한다
    return;
  }
  target.width = painted.canvas.width;
  target.height = painted.canvas.height;
  ctx.clearRect(0, 0, target.width, target.height);
  ctx.drawImage(painted.canvas, 0, 0);
  if (source) {
    // 좌표를 다시 넣으면 소스가 캔버스를 다시 읽는다(animate: false).
    source.setCoordinates(painted.coordinates);
    return;
  }
  m.addSource("grid-field", {
    type: "canvas",
    canvas: target,
    coordinates: painted.coordinates,
    animate: false,
  });
  m.addLayer({
    id: "grid-field",
    type: "raster",
    source: "grid-field",
    // 램프 색이 자체 alpha 를 갖는다. 여기 opacity 는 1등급 밀집 구역에서
    // 도로·라벨이 읽히게 하는 몫이다.
    paint: {
      "raster-opacity": 0.8,
      "raster-resampling": "linear",
      "raster-fade-duration": 0,
    },
  }, "grid-fill");                                 // 테두리 층들보다 아래로
}
import "maplibre-gl/dist/maplibre-gl.css";
import { ApiError, api } from "../api/client";
import type { GridCell, Grade, Point } from "../api/types";
import { LEGEND_STEPS, gradeLabel } from "../lib/grade";
import { survivalSentence } from "../lib/format";
import { ErrorState, Loading } from "./states";
import s from "./GridMap.module.css";

// MapLibre + OSM raster (KAKAO_JAVASCRIPT_KEY 이 발급되지 않아 스펙의 대체안).
// 칸은 실제 100m 폴리곤으로만 그린다. 흐린 그라디언트는 없는 해상도를 주장하고,
// 연속 알파는 우리가 검증한 것이 등급뿐인데 점수가 있는 것처럼 보이게 한다.

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

/** 2px 팬으로 재조회하지 않게 뷰포트를 양자화한다. 반드시 바깥쪽으로만 — 대칭
 *  반올림은 변마다 최대 0.001°(≈ 100m 한 칸) bbox 를 줄여 경계 칸을 흘린다. */
const quantise = ([w, s, e, n]: Bbox): Bbox => [
  Math.floor(w * 500) / 500,
  Math.floor(s * 500) / 500,
  Math.ceil(e * 500) / 500,
  Math.ceil(n * 500) / 500,
];

/** 서울 전역 줌에서는 /grids 가 413 이라 칸이 하나도 안 나오고, 빈 지도는
 *  «여긴 데이터가 없다»로 읽힌다. 그래서 지도는 실제 후보에 붙어서 열린다. */
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
  /** 지도 위에서 마우스가 짚은 칸. 목록 호버(hoveredId)와 별개로 둔다 —
   *  한 상태로 합치면 목록에서 손을 떼는 순간 지도 쪽 테두리까지 사라진다. */
  const [mapHoverId, setMapHoverId] = useState<string | null>(null);
  /* 스타일이 비동기로 로드돼 마운트 시점엔 소스가 없다. 캐시된 데이터가 그보다
     먼저 도착할 수 있고, 이 플래그가 없으면 그 데이터가 버려져 재진입 때마다
     지도가 빈 채로 남는다. */
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
      // 등급 면은 벡터가 아니라 그림 한 장으로 낸다(`ensureField`). 칸마다
      // 칠하고 전체를 번지게 해서 등고선처럼 잇되, 칸이 있는 자리 모양으로
      // 오려낸다. 그래서 색이 구역 밖으로 나가지 않는다 — heatmap·circle-blur
      // 로 두 번 시도해 봤을 때 실패한 지점이 정확히 그것이었다.
      //
      // 칸 자체는 투명하게 남긴다 — 보이는 것은 그 그림이고, 이 층은 클릭과
      // 마우스 위치를 잡는 몫만 한다.
      m.addLayer({
        id: "grid-fill",
        type: "fill",
        source: "grids",
        paint: { "fill-color": "#000", "fill-opacity": 0 },
      });
      // 순위에 든 칸을 표시한다. 램프가 브랜드 노랑이라 노란 선은 묻히므로
      // 어두운 선을 쓰되, **아래 선택 테두리보다 확실히 약해야 한다** —
      // 둘 다 진한 검정이면 «고르지도 않았는데 검은 테두리»로 읽힌다.
      // 순위 1~3위는 핀이 따로 말하고, 이 선은 4위 이하를 묶어 주는 몫이다.
      m.addLayer({
        id: "grid-top",
        type: "line",
        source: "grids",
        filter: ["in", ["get", "gridId"], ["literal", []]],
        paint: {
          "line-color": "#3A2A12",
          "line-width": 1,
          "line-opacity": 0.3,
        },
      });
      // Hover/selection echo from the list (Zillow-style two-way sync).
      // 화면에서 «지금 이 칸»은 이것 하나뿐이어야 한다.
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
      // 셀 경계는 평소에 안 그린다. 지도 위에서 짚은 칸에만 테두리를 얹어
      // «지금 이 칸» 을 알려준다 — 격자 전체에 선을 그으면 체스판이 된다.
      // 목록 호버(hoveredId)와 같은 레이어를 쓰되, 목록 쪽이 이기게 둔다.
      m.on("mousemove", "grid-fill", (e: MapLayerMouseEvent) => {
        m.getCanvas().style.cursor = "pointer";
        const id = e.features?.[0]?.properties?.gridId;
        if (typeof id === "string") setMapHoverId(id);
      });
      m.on("mouseleave", "grid-fill", () => setMapHoverId(null));
      m.on("mouseenter", "grid-fill", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "grid-fill", () => (m.getCanvas().style.cursor = ""));
      // 여기서 syncBbox 를 부르지 않는다. 지도는 서울 전역(zoom 12)에서 열리고
      // 그 조회는 확정 413 이라, 첫 조회는 moveend 에 맡긴다.
      setReady(true);
    });
    m.on("moveend", syncBbox);

    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      setReady(false);
    };
    // 매 렌더마다 지도를 다시 만들면 사용자의 뷰포트가 날아간다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- data ---------------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    const src = m?.getSource("grids") as GeoJSONSource | undefined;
    if (!m || !src) return;
    const cells = q.data ? q.data.items : [];
    src.setData(cells.length ? toFc(cells) : emptyFc());
    ensureField(m, cells);
  }, [q.data, ready]);

  useEffect(() => {
    const m = map.current;
    if (!m?.getLayer("grid-active")) return;
    m.setFilter("grid-active", [
      "==",
      ["get", "gridId"],
      hoveredId ?? mapHoverId ?? selectedId ?? "",
    ]);
    // `ready` matters: cached selection can land before the style loads.
  }, [hoveredId, mapHoverId, selectedId, ready]);

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
      {/* Lenis 가 휠을 가로채 페이지를 대신 굴린다. MapLibre 의 preventDefault
          가 안 먹어서, 지도에서 줌하면 페이지도 같이 내려갔다(실측: 휠 240 에
          235px). 이 속성이 Lenis 에게 «여기는 손대지 마라»를 알린다. */}
      <div ref={holder} className={s.canvas} data-lenis-prevent />
      <div className={s.overlay}>
        {q.isPending && bbox ? <Loading label="격자 불러오는 중…" /> : null}
        {/* 413 은 변명할 실패가 아니다. 표본으로 솎은 지도는 커버리지를 잘못
            말하므로 서버가 솎기를 거부한다(§B 계약). */}
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

/** 주소 1줄 + 값 1개 + 방향 1개 + 진입 액션 1개. 이보다 빽빽하면 지도가 안
 *  읽힌다. 주소는 값이 아니라 «지금 짚은 칸이 어디냐»에 대한 답이다. */
function Bubble({ cell, onOpen }: { cell?: GridCell; onOpen?: (cell: GridCell) => void }) {
  const addr = useQuery({
    queryKey: ["gridAddress", cell?.gridId],
    queryFn: () => api.gridAddress(cell!.gridId),
    enabled: cell !== undefined,
    staleTime: Infinity,   // 격자의 주소는 세션 안에서 바뀌지 않는다
  });
  if (!cell) return null;
  return (
    <div className={s.bubble}>
      <span className={s.bubbleAddr}>
        {addr.data
          ? (addr.data.label ?? "주소 미상")
          : addr.isError
            ? "주소를 불러오지 못했어요"
            : "주소 확인 중…"}
      </span>
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

/** 색칸은 램프를 LEGEND_STEPS 지점에서만 뽑는다. 9개를 다 적으면 안 읽힌다. */
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
