import type { Competition } from "../api/types";

/** «이 업종 가게가 몇 곳인가»는 원천이 둘이다.
 *
 *  인허가는 일반음식점만 담아서 카페·테이크아웃 치킨이 통째로 빠진다(서울
 *  카페의 5.7%만 보인다). 상가업소는 휴게음식점까지 포함한 현재 영업 스냅샷
 *  이라 그쪽이 «지금 몇 곳인가»의 더 완전한 답이다. 다만 상가업소는 개·폐업
 *  이력이 없어 모든 업종에 매핑되지도 않는다(서버가 애매한 것은 null 로 준다).
 *
 *  그래서 규칙은 하나다 — 상가업소가 있으면 그것을, 없으면 인허가를 쓰고,
 *  «어느 쪽인지 반드시 화면에 적는다». 두 원천을 말없이 섞으면 같은 라벨의
 *  숫자가 업종마다 다른 뜻이 된다.
 */
export function storeCount(c: Competition): {
  here: number | null;
  ring: number | null;
  source: "상가업소" | "인허가";
} {
  if (c.currentStoresHere !== null) {
    return { here: c.currentStoresHere, ring: c.currentStoresNeighbor, source: "상가업소" };
  }
  return { here: c.sameUptaeHere, ring: c.sameUptaeNeighbor, source: "인허가" };
}
