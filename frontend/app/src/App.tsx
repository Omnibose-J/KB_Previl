import { useState } from "react";
import S1Landing from "./screens/S1Landing";
import S2Input from "./screens/S2Input";
import S3Results from "./screens/S3Results";
import S4Detail from "./screens/S4Detail";
import { SearchProvider } from "./state/search";

// Flow contract: frontend/design/ui-spec.md §2
//   A(탐색): S1 -> S2 -> S3 -> S4
//   B(진단): S1 -> S4 (via /at lookup)   [P1 — not wired yet]
// Plain state routing is enough for a 4-screen fixed-width demo; add a router
// only if deep links become a requirement.
export type Screen =
  | { name: "landing" }
  | { name: "input" }
  | { name: "results" }
  | { name: "detail"; gridId: string; from: "results" | "diagnosis" };

export default function App() {
  const [screen, setScreen] = useState<Screen>({ name: "landing" });

  return (
    <SearchProvider>
      <Route screen={screen} go={setScreen} />
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
    case "detail":
      return <S4Detail go={go} gridId={screen.gridId} from={screen.from} />;
  }
}
