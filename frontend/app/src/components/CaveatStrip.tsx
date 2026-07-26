import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorState, Loading } from "./states";
import s from "./CaveatStrip.module.css";

// Mandatory disclosure strip pinned to the bottom of S2/S3 (ui-spec §4).
// Text comes from meta().caveats — the API is the single source; if it fails,
// we show the error state rather than a hardcoded fallback string. Rewriting
// or shortening these lines on the client is exactly the failure this rule
// exists to prevent.
export default function CaveatStrip() {
  const q = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorState onRetry={() => q.refetch()} detail={String(q.error)} />;
  return (
    <footer className={s.strip}>
      {q.data.caveats.map((c) => (
        <span key={c} className={s.item}>
          {c}
        </span>
      ))}
    </footer>
  );
}
