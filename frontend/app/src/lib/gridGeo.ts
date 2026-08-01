// 격자 셀 -> 지도 GeoJSON. React 도 지도 인스턴스도 모르는 순수 변환이라
// GridMap 에서 떼어 뒀다.

import type { FeatureCollection } from "geojson";
import type { GridCell } from "../api/types";

export const emptyFc = (): FeatureCollection => ({
  type: "FeatureCollection",
  features: [],
});

// 캔버스 해상도. 칸 하나를 몇 픽셀로 그릴지 — 번짐 반경이 이 안에서 결정된다.
const CELL_PX = 14;
// 칸 크기 대비 번짐 반경. 1 이면 이웃 중심까지 섞여 칸 모양이 사라진다.
//
// 매끄러움과 «등급이 읽히는가» 는 정면으로 맞선다. 40px 떨어진 두 점의 색차
// 상위 10% 로 재면 각진 원본이 27, 0.55 에서 13, 0.30 에서 18, 여기서 22 다.
// 평균 색차는 어느 값에서나 비슷하다 — 이웃은 대개 1등급 차라 원래 티가 안
// 나고, 눌리는 것은 «확 다른 자리끼리» 의 대비뿐이라 그것만 보면 된다.
const FIELD_BLUR = 0.2;
// 캔버스 한 변 상한. 넓은 구역에서 해상도를 낮춰서라도 메모리를 지킨다.
const FIELD_MAX = 2048;
// 바깥 윤곽을 안쪽으로 얼마나 부드럽게 먹일지(칸 크기 대비). 100m 칸의 계단
// 모서리를 눕히는 몫이다. 밖으로는 번지지 않는다 — 잘라낸 뒤에 먹인다.
const RIM_FEATHER = 0.12;

/** 캔버스 네 귀퉁이 — 좌상, 우상, 우하, 좌하. 지도 소스가 이 순서를 요구한다. */
export type Corners = [
  [number, number], [number, number], [number, number], [number, number],
];

export type Field = { canvas: HTMLCanvasElement; coordinates: Corners };

/**
 * 등급 면을 한 장의 그림으로 그린다.
 *
 * 칸마다 사각형을 칠하고 **전체를 번지게** 해서 등고선처럼 이어지게 만든 뒤,
 * 칸이 실제로 있는 자리 모양으로 **정확히 오려낸다**. 그래서 안쪽은 부드럽고
 * 구역 바깥으로는 한 픽셀도 나가지 않는다.
 *
 * 번지기 전에 칸 바깥으로 한 겹 더 깔아 두는 것이 중요하다. 그게 없으면
 * 가장자리에서 «투명»과 섞여 구역 테두리가 빛바랜 채로 잘린다.
 */
export function paintField(
  cells: GridCell[],
  colorOf: (g: number) => string,
): Field | null {
  if (!cells.length) return null;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  let span = Infinity;
  for (const c of cells) {
    for (const [lon, lat] of c.polygon) {
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
    }
    const lons = c.polygon.map((p) => p[0]);
    span = Math.min(span, Math.max(...lons) - Math.min(...lons));
  }
  if (!(span > 0)) return null;

  let scale = CELL_PX / span;                        // 도(degree)당 픽셀
  const cap = FIELD_MAX / Math.max(east - west, north - south);
  if (scale > cap) scale = cap;
  const w = Math.max(1, Math.round((east - west) * scale));
  const h = Math.max(1, Math.round((north - south) * scale));
  const blur = Math.max(1, span * scale * FIELD_BLUR);

  const box = (c: GridCell) => {
    const lons = c.polygon.map((p) => p[0]);
    const lats = c.polygon.map((p) => p[1]);
    const x = (Math.min(...lons) - west) * scale;
    const y = (north - Math.max(...lats)) * scale;
    return {
      x,
      y,
      // 이웃과 맞물리도록 반 픽셀 겹친다. 안 그러면 칸 사이에 실금이 남는다.
      w: (Math.max(...lons) - Math.min(...lons)) * scale + 1,
      h: (Math.max(...lats) - Math.min(...lats)) * scale + 1,
    };
  };

  // 램프 색의 알파를 떼고 칠한다. 반투명끼리 번지면 옅은 등급이 바탕에 묻혀
  // 등급 차가 사라진다(실측: 40px 상위10% 색차 27 -> 12). 투명도는 레이어
  // 하나(`raster-opacity`)가 맡고, 여기서는 색만 섞는다.
  const solid = (g: number) => {
    const c = colorOf(g);
    const fn = c.match(/rgba?\(([^)]+)\)/);
    if (!fn) return c;
    const [r, gg, b] = fn[1].split(",").map((s) => Number(s.trim()));
    return `rgb(${r}, ${gg}, ${b})`;
  };

  const sheet = () => {
    const cv = document.createElement("canvas");
    cv.width = w;
    cv.height = h;
    return [cv, cv.getContext("2d")] as const;
  };
  const [raw, rc] = sheet();
  const [out, oc] = sheet();
  const [mask, mc] = sheet();
  const [pad, pc] = sheet();
  if (!rc || !oc || !mc || !pc) return null;

  // 오려낼 모양을 한 장에 먼저 모은다. `destination-in` 은 그릴 때마다 «그
  // 도형 바깥»을 통째로 지우므로, 칸마다 부르면 직전 칸까지 날아간다.
  mc.fillStyle = "#000";
  for (const c of cells) {
    const b = box(c);
    mc.fillRect(b.x, b.y, b.w, b.h);
  }

  // 구역 «바깥»에 깔 여백. 이게 없으면 번질 때 투명과 섞여 테두리가 빛바랜다.
  for (const c of cells) {
    const b = box(c);
    pc.fillStyle = solid(c.grade);
    pc.fillRect(b.x - blur, b.y - blur, b.w + blur * 2, b.h + blur * 2);
  }
  // 구역 안쪽은 파낸다. 이 겹은 «바깥 여백»만 맡아야 하고, 안쪽까지 남으면
  // 이웃 색이 칸 밑에 깔린다.
  pc.globalCompositeOperation = "destination-out";
  pc.drawImage(mask, 0, 0);

  for (const c of cells) {
    const b = box(c);
    rc.fillStyle = solid(c.grade);
    rc.fillRect(b.x, b.y, b.w, b.h);
  }
  rc.globalCompositeOperation = "destination-over";
  rc.drawImage(pad, 0, 0);
  // 모양을 흐린 뒤 원래 모양으로 다시 잘라, 윤곽이 **안쪽으로만** 부드러워지게
  // 한다. 계단 모서리가 눕고, 바깥으로는 한 픽셀도 나가지 않는다.
  const feather = Math.max(1, span * scale * RIM_FEATHER);
  const soft = document.createElement("canvas");
  soft.width = w;
  soft.height = h;
  const sc = soft.getContext("2d");
  if (!sc) return null;
  sc.filter = `blur(${feather.toFixed(1)}px)`;
  sc.drawImage(mask, 0, 0);
  sc.filter = "none";
  sc.globalCompositeOperation = "destination-in";
  sc.drawImage(mask, 0, 0);

  oc.filter = `blur(${blur.toFixed(1)}px)`;
  oc.drawImage(raw, 0, 0);
  oc.filter = "none";
  // 칸이 있는 자리만 남긴다. 번짐이 구역을 넘어간 부분은 여기서 잘려 나간다.
  oc.globalCompositeOperation = "destination-in";
  oc.drawImage(soft, 0, 0);

  return {
    canvas: out,
    coordinates: [[west, north], [east, north], [east, south], [west, south]],
  };
}

/** 갱신마다 스타일을 한 번만 읽는다. 채우기와 경계가 같은 램프를 봐야 두 층의
 *  색이 갈라지지 않는다. */
export function makeColorOf() {
  const rootStyle = getComputedStyle(document.documentElement);
  const ramp = new Map<number, string>();
  return (g: number) => {
    let c = ramp.get(g);
    if (!c) {
      c = rootStyle.getPropertyValue(`--color-heatmap-${g}`).trim();
      ramp.set(g, c);
    }
    return c;
  };
}

export function toFc(cells: GridCell[]): FeatureCollection {
  const colorOf = makeColorOf();
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

/** GeoJSON rings must be closed; B sends four corners. */
function closeRing(ring: [number, number][]): [number, number][] {
  if (ring.length === 0) return ring;
  const [first] = ring;
  const last = ring[ring.length - 1];
  return first[0] === last[0] && first[1] === last[1] ? ring : [...ring, first];
}
