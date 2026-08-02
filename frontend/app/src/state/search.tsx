import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

// The two required inputs (업종 + 범위) plus the optional budget, carried from
// S2 to S3/S4/S5 (ui-spec §3-S2). Budget fields are optional on purpose: the
// runway card stays uncomputed until the user supplies them — we never fill
// them in.

export interface SearchState {
  /** exact meta().uptae value — never a prettified label (ui-spec §7) */
  uptae: string | null;
  /** empty = 서울 전역 (no radius concept exists in the backend) */
  districts: string[];
  /** 만원/월, user input only */
  rentMonthly: number | null;
  /** 만원, user input only */
  upfront: number | null;
  /** 만원, 창업에 쓸 수 있는 총 예산 — user input only */
  budget: number | null;
}

interface SearchApi extends SearchState {
  set: (patch: Partial<SearchState>) => void;
  toggleDistrict: (d: string) => void;
}

const Ctx = createContext<SearchApi | null>(null);

export function SearchProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SearchState>({
    uptae: null,
    districts: [],
    rentMonthly: null,
    upfront: null,
    budget: null,
  });

  const value = useMemo<SearchApi>(
    () => ({
      ...state,
      set: (patch) => setState((s) => ({ ...s, ...patch })),
      toggleDistrict: (d) =>
        setState((s) => ({
          ...s,
          districts: s.districts.includes(d)
            ? s.districts.filter((x) => x !== d)
            : [...s.districts, d],
        })),
    }),
    [state],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSearch(): SearchApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSearch must be used inside <SearchProvider>");
  return ctx;
}
