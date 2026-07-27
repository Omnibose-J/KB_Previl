import { useEffect, useRef, useState } from "react";
import s from "./Dropdown.module.css";

// Custom select: native <select> popups cannot be styled, and the raw widget
// was the last "browser form" tell in the UI. Trigger styling matches the
// host field (bold ink when chosen, grey prompt when empty; yellow-on-dark
// variant for the What-if panel). Full keyboard + listbox ARIA.

export interface DropOption {
  value: string;
  label: string;
}

export default function Dropdown({
  options,
  value,
  display,
  placeholder,
  emptyNote,
  dark = false,
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
  onSelect: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(-1);
  const wrap = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLUListElement>(null);

  const selIdx = options.findIndex((o) => o.value === value);
  const label = display ?? (selIdx >= 0 ? options[selIdx].label : null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
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
    if (e.key === "Escape") setOpen(false);
    else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!open) toggle();
      else if (hi >= 0 && options[hi]) choose(options[hi].value);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) toggle();
      else setHi((h) => Math.min(options.length - 1, h + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHi((h) => Math.max(0, h - 1));
    }
  };

  return (
    <div className={s.wrap} ref={wrap} onKeyDown={onKey}>
      <button
        type="button"
        className={dark ? s.trigDark : label ? s.trig : s.trigEmpty}
        aria-haspopup="listbox"
        aria-expanded={open}
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

      {open ? (
        <ul className={s.menu} role="listbox" ref={menu}>
          {options.length === 0 ? (
            <li className={s.optNote}>{emptyNote ?? "표시할 항목이 없습니다"}</li>
          ) : (
            options.map((o, i) => (
              <li
                key={o.value}
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
      ) : null}
    </div>
  );
}
