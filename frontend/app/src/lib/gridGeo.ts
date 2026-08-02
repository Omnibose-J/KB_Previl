// 격자 셀 -> 지도 GeoJSON. React 도 지도 인스턴스도 모르는 순수 변환이라
// GridMap 에서 떼어 뒀다.

import type { Feature, FeatureCollection } from "geojson";
import type { BuildingFootprint, GridCell } from "../api/types";

export const emptyFc = (): FeatureCollection => ({
  type: "FeatureCollection",
  features: [],
});

/** 갱신마다 스타일을 한 번만 읽는다. 채우기와 경계가 같은 램프를 봐야 두 층의
 *  색이 갈라지지 않는다. */
function makeColorOf() {
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

/** 램프 색의 알파를 떼고 낸다. 투명도는 채우기 층 하나(`fill-opacity`)가 맡는다
 *  — 등급마다 알파가 다르면 옅은 등급이 바탕에 묻혀 등급 차가 사라진다. 램프의
 *  알파는 범례 스와치가 그대로 쓴다. */
function opaque(color: string) {
  const fn = color.match(/rgba?\(([^)]+)\)/);
  if (!fn) return color;
  const [r, g, b] = fn[1].split(",").map((s) => Number(s.trim()));
  return `rgb(${r}, ${g}, ${b})`;
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
        color: opaque(colorOf(c.grade)),
        cell: JSON.stringify(c),
      },
    })),
  };
}

/** 건물 외곽선. 링 하나가 폴리곤 하나가 된다 — 선 층이 그리므로 채우기는 없다.
 *  여기서 셀·등급과 엮지 않는다. 모양만 내고, 어떤 주장도 붙이지 않는다. */
export function toBuildingFc(buildings: BuildingFootprint[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: buildings.flatMap((building) =>
      building.rings.map((ring) => ({
        type: "Feature" as const,
        geometry: { type: "Polygon" as const, coordinates: [ring] },
        properties: { name: building.name, floors: building.floors },
      })),
    ),
  };
}

/**
 * 칸 경계를 «변» 단위로 낸다.
 *
 * 폴리곤마다 링을 그리면 맞닿은 변이 두 번 그려진다. 점선의 위상은 선 하나가
 * 시작하는 지점부터 세므로 두 번째 선의 칠해진 자리가 첫 번째 선의 빈 자리에
 * 얹혀 실선으로 보인다. 그래서 같은 변은 한 번만 낸다.
 */
export function toEdgeFc(cells: GridCell[]): FeatureCollection {
  const seen = new Set<string>();
  const features: Feature[] = [];
  for (const c of cells) {
    const ring = closeRing(c.polygon);
    for (let i = 0; i + 1 < ring.length; i += 1) {
      const key = edgeKey(ring[i], ring[i + 1]);
      if (seen.has(key)) continue;
      seen.add(key);
      features.push({
        type: "Feature",
        geometry: { type: "LineString", coordinates: [ring[i], ring[i + 1]] },
        properties: {},
      });
    }
  }
  return { type: "FeatureCollection", features };
}

/** 그린 방향과 부동소수 오차에 무관한 변 식별자. 1e-7 도는 1cm 남짓이라 같은
 *  변은 반드시 같은 키가 되고, 다른 변끼리 겹칠 일은 없다(칸 한 변이 100m). */
function edgeKey(a: [number, number], b: [number, number]) {
  const at = `${a[0].toFixed(7)},${a[1].toFixed(7)}`;
  const bt = `${b[0].toFixed(7)},${b[1].toFixed(7)}`;
  return at < bt ? `${at}|${bt}` : `${bt}|${at}`;
}

/** GeoJSON rings must be closed; B sends four corners. */
function closeRing(ring: [number, number][]): [number, number][] {
  if (ring.length === 0) return ring;
  const [first] = ring;
  const last = ring[ring.length - 1];
  return first[0] === last[0] && first[1] === last[1] ? ring : [...ring, first];
}
