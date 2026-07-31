import { useEffect } from "react";

// 스크롤 진입 연출. CSS animation-timeline: view() 는 크롬 계열에서만 돌고 값이
// 컴포지터에만 있어 getComputedStyle 로 «되는지»를 잴 수 없어서 기각했다.
//
// 숨김은 JS 가 켠 것만 적용된다(data-reveal="off"). 스크립트가 죽으면 아무것도
// off 가 되지 않아 내용이 그냥 보인다 — 연출이 내용을 삼키지 않게 하는 장치다.

const ENTER_RATIO = 0.12;

/** `deps` 는 «대상이 화면에 붙는 시점»을 알린다. 리포트처럼 데이터가 온 뒤에
 *  절이 생기는 화면은 마운트 시점에 관찰할 것이 없어서, 데이터를 함께 넘겨야
 *  한다. 안 넘기면 연출만 빠지고 내용은 그대로 보인다(깨지지는 않는다). */
export function useReveal(deps: unknown[] = []) {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const targets = Array.from(
      document.querySelectorAll<HTMLElement>("[data-reveal]"),
    );
    if (!targets.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          (entry.target as HTMLElement).dataset.reveal = "in";
          observer.unobserve(entry.target);
        }
      },
      { threshold: ENTER_RATIO },
    );

    for (const el of targets) {
      // 이미 화면에 걸쳐 있는 요소를 숨겼다가 다시 켜면 깜빡인다. 관찰만 건다.
      const box = el.getBoundingClientRect();
      const visible = box.top < window.innerHeight && box.bottom > 0;
      el.dataset.reveal = visible ? "in" : "off";
      if (!visible) observer.observe(el);
    }

    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
