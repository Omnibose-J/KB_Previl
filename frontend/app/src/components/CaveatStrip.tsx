import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorState, Loading } from "./states";

// Mandatory disclosure strip pinned to the bottom of S2/S3 (ui-spec §4).
// Text comes from meta().caveats — the API is the single source; if it fails,
// we show the error state rather than a hardcoded fallback string.
export default function CaveatStrip() {
  const q = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorState onRetry={() => q.refetch()} />;
  return (
    <footer className="caveat-strip">
      {q.data.caveats.map((c) => (
        <span key={c}>{c}</span>
      ))}
    </footer>
  );
}
