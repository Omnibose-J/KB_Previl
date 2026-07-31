import { useEffect, useId, useRef, useState } from "react";
import s from "./Dropdown.module.css";

// Custom select: native <select> popups cannot be styled, and the raw widget
// was the last "browser form" tell in the UI. Trigger styling matches the
// host field (bold ink when chosen, grey prompt when empty; yellow-on-dark
// variant for the What-if panel). Full keyboard + listbox ARIA.

export interface DropOption {
  value: string;
  label: string;
}

/** 공백을 지워 «강남 신사» 와 «강남신사» 를 같게 본다. */
const norm = (v: string) => v.replace(/\s+/g, "");

const trigger = (dark: boolean, compact: boolean, chosen: boolean) => {
  if (dark) return s.trigDark;
  if (compact) return chosen ? s.trigSm : s.trigSmEmpty;
  return chosen ? s.trig : s.trigEmpty;
};

export default function Dropdown({
  options,
  value,
  display,
  placeholder,
  emptyNote,
  dark = false,
  compact = false,
  searchable = false,
  searchPlaceholder,
  onSelect,
}: {
  options: DropOption[];
  value: string | null;
  /** trigger text override (e.g. "3개 자치구") when value alone can't say it */
  display?: string;
  placeholder: string;
  /** shown inside the menu when options are empty (e.g. meta fetch failed) */
  emptyNote?: string;
  dark?: boolean;
  /** 제목·헤더 옆에 놓을 때. 본문 필드로 쓰는 기본 크기(18px)를 줄인다. */
  compact?: boolean;
  /** 목록이 수백 줄일 때만. 25줄짜리에 검색칸을 붙이면 한 단계만 늘어난다. */
  searchable?: boolean;
  searchPlaceholder?: string;
  onSelect: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(-1);
  const [query, setQuery] = useState("");
  const wrap = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLUListElement>(null);
  const box = useRef<HTMLInputElement>(null);
  const idBase = { current: useId() };

  const label = display ?? options.find((o) => o.value === value)?.label ?? null;
  const shown =
    searchable && query.trim()
      ? options.filter((o) => norm(o.label).includes(norm(query)))
      : options;
  const selIdx = shown.findIndex((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  // The highlight index belongs to a specific options list; when the list is
  // swapped underneath (meta arriving, or the query narrowing it), the old
  // index points at the wrong row.
  useEffect(() => {
    setHi(-1);
  }, [shown.length]);

  // 열 때마다 빈 칸에서 시작한다 — 지난번 검색어가 남아 있으면 목록이 이미
  // 걸러진 채로 열려 «항목이 사라졌다» 로 읽힌다.
  useEffect(() => {
    if (open) box.current?.focus();
    else setQuery("");
  }, [open]);

  // keep the highlighted row in view while arrowing through a long list
  useEffect(() => {
    if (open && hi >= 0)
      menu.current?.children[hi]?.scrollIntoView({ block: "nearest" });
  }, [open, hi]);

  const toggle = () => {
    setOpen((v) => !v);
    setHi(selIdx);
  };

  const choose = (v: string) => {
    onSelect(v);
    setOpen(false);
  };

  const onKey = (e: React.KeyboardEvent) => {
    // 검색칸에서의 스페이스는 «고르기» 가 아니라 글자다.
    const typing = e.target === box.current;
    if (e.key === "Escape") setOpen(false);
    else if (e.key === "Enter" || (e.key === " " && !typing)) {
      e.preventDefault();
      if (!open) toggle();
      else if (hi >= 0 && shown[hi]) choose(shown[hi].value);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) toggle();
      else setHi((h) => Math.min(shown.length - 1, h + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) toggle();
      else setHi((h) => Math.max(0, h - 1));
    }
  };

  const list = (className: string) => (
    <ul
      className={className}
      role="listbox"
      ref={menu}
      // Keep focus on the trigger (or the search box): without this, mousedown
      // on an option blurs it, the onBlur close fires first, and the click
      // lands on a menu that no longer exists.
      onMouseDown={(e) => e.preventDefault()}
    >
      {shown.length === 0 ? (
        <li className={s.optNote} role="presentation">
          {options.length === 0
            ? (emptyNote ?? "표시할 항목이 없습니다")
            : "찾는 이름이 없어요"}
        </li>
      ) : (
        shown.map((o, i) => (
          <li
            key={o.value}
            id={`${idBase.current}-${i}`}
            role="option"
            aria-selected={o.value === value}
            className={o.value === value ? s.optOn : i === hi ? s.optHi : s.opt}
            onMouseEnter={() => setHi(i)}
            onClick={() => choose(o.value)}
          >
            {o.label}
          </li>
        ))
      )}
    </ul>
  );

  return (
    <div
      className={s.wrap}
      ref={wrap}
      onKeyDown={onKey}
      onBlur={(e) => {
        // Tabbing away must not leave an orphaned menu behind.
        if (!wrap.current?.contains(e.relatedTarget as Node)) setOpen(false);
      }}
    >
      <button
        type="button"
        className={trigger(dark, compact, label !== null)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-activedescendant={open && hi >= 0 ? `${idBase.current}-${hi}` : undefined}
        onClick={toggle}
      >
        <span className={s.trigLabel}>{label ?? placeholder}</span>
        <svg
          className={open ? s.chevOpen : s.chev}
          width="12"
          height="8"
          viewBox="0 0 12 8"
          aria-hidden
        >
          <path
            d="M1 1.5 6 6.5 11 1.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      </button>

      {!open ? null : searchable ? (
        <div className={s.panel}>
          <input
            ref={box}
            className={s.search}
            type="text"
            value={query}
            placeholder={searchPlaceholder ?? "이름으로 찾기"}
            aria-label={searchPlaceholder ?? placeholder}
            onChange={(e) => setQuery(e.target.value)}
          />
          {list(s.panelList)}
        </div>
      ) : (
        list(s.menu)
      )}
    </div>
  );
}
