import { useCallback, useState } from "react";
import { flushSync } from "react-dom";
import S1Landing from "./screens/S1Landing";
import S2Input from "./screens/S2Input";
import S3Results from "./screens/S3Results";
import S4Detail from "./screens/S4Detail";
import S5Compare from "./screens/S5Compare";
import { SearchProvider } from "./state/search";

// Flow contract: frontend/design/ui-spec.md §2
//   A(탐색): S1 -> S2 -> S3 -> S4
//   B(진단): S1 -> S4 (via /at lookup)   [P1 — not wired yet]
//   C(비교): S1 -> S5                    후보를 이미 손에 쥔 사용자 (기획서 §1.4)
// Plain state routing is enough for a fixed-width demo; add a router only if
// deep links become a requirement.
export type Screen =
  | { name: "landing" }
  | { name: "input" }
  | { name: "results" }
  | { name: "compare" }
  | { name: "detail"; gridId: string; from: "results" | "diagnosis" };

export default function App() {
  const [screen, setScreen] = useState<Screen>({ name: "landing" });

  // 화면 교체를 교차 페이드로 잇는다. startViewTransition 은 «콜백 실행 전후의
  // DOM»을 비교하므로 setState 를 flushSync 로 동기 커밋해야 한다 — 안 그러면
  // React 가 나중에 렌더해서 전환이 빈 화면 사이에서 일어난다.
  // 지원하지 않는 브라우저에서는 그냥 즉시 교체된다(전환만 없고 내용은 같다).
  const go = useCallback((next: Screen) => {
    if (!document.startViewTransition) {
      setScreen(next);
      return;
    }
    document.startViewTransition(() => flushSync(() => setScreen(next)));
  }, []);

  return (
    <SearchProvider>
      <Route screen={screen} go={go} />
    </SearchProvider>
  );
}

function Route({ screen, go }: { screen: Screen; go: (s: Screen) => void }) {
  switch (screen.name) {
    case "landing":
      return <S1Landing go={go} />;
    case "input":
      return <S2Input go={go} />;
    case "results":
      return <S3Results go={go} />;
    case "compare":
      return <S5Compare go={go} />;
    case "detail":
      return <S4Detail go={go} gridId={screen.gridId} from={screen.from} />;
  }
}
