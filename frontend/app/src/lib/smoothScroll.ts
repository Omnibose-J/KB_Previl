import { useEffect } from "react";
import Lenis from "lenis";

// 휠·트랙패드 스크롤에 관성을 준다. 직접 짜지 않는 이유는 트랙패드 관성·터치·
// 키보드·중첩 스크롤을 전부 맞춰야 하고 하나만 틀려도 «스크롤이 고장난 사이트»가
// 되기 때문이다. reduced-motion 에서는 켜지 않는다.

export function useSmoothScroll() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const lenis = new Lenis({
      // 0.09 는 «따라오는 느낌»과 «늦게 반응한다»의 경계. 더 낮추면 스크롤을
      // 멈춘 뒤에도 한참 미끄러져 목표 지점을 지나친다.
      lerp: 0.09,
      wheelMultiplier: 1,
      // 스크롤 위치를 CSS 로 되돌리지 않는다 — scrollIntoView 나 앵커 이동은
      // 아래 scrollTo 위임으로 처리한다.
      autoRaf: true,
    });

    // scrollIntoView({behavior:"smooth"}) 는 네이티브 스크롤을 직접 움직여
    // Lenis 의 내부 위치와 어긋난다. 화면 코드가 쓰는 경로를 Lenis 로 넘긴다.
    const nativeScrollIntoView = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (arg?: boolean | ScrollIntoViewOptions) {
      const smooth = typeof arg === "object" && arg?.behavior === "smooth";
      if (!smooth) return nativeScrollIntoView.call(this, arg as boolean);
      lenis.scrollTo(this as HTMLElement);
    };

    return () => {
      Element.prototype.scrollIntoView = nativeScrollIntoView;
      lenis.destroy();
    };
  }, []);
}
