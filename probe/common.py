"""Shared helpers for API probes. Never print secret values."""
import io
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)


def load_env():
    env = {}
    for name in (".env",):
        p = ROOT / name
        if not p.exists():
            continue
        for line in io.open(p, encoding="utf-8-sig"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = load_env()


def key(*names):
    """Return the first non-empty key among names, else None."""
    for n in names:
        v = ENV.get(n)
        if v:
            return v
    return None


def keystat(*names):
    """Report presence/length only - never the value."""
    for n in names:
        v = ENV.get(n)
        if v:
            return f"{n}(len={len(v)})"
    return "MISSING:" + "/".join(names)


def save(name, obj):
    p = RESULTS / f"{name}.json"
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return p


def brief(d, limit=25):
    """Field names of a dict-like record, truncated."""
    if isinstance(d, dict):
        ks = list(d.keys())
        return ks[:limit], len(ks)
    return [], 0


def timed(fn, *a, **kw):
    t0 = time.time()
    try:
        r = fn(*a, **kw)
        return r, round(time.time() - t0, 2), None
    except Exception as e:
        return None, round(time.time() - t0, 2), f"{type(e).__name__}: {e}"
