"""Disk cache for built splits. Rebuilding a split costs ~6s per cohort year,
which is fine once and ruinous across the ~150 fits the ablation programme needs.

The cache key includes a hash of every module that produces a feature value, so
a feature edit invalidates it automatically. A stale split silently scored under
a new feature definition is exactly the class of quiet-falsehood this project
guards against - the fingerprint makes it impossible rather than unlikely.
"""
import hashlib
import io
import os
import pickle
from pathlib import Path

CACHE_DIR = Path(os.environ.get("KB_MODEL_CACHE") or (Path(__file__).parent / ".cache"))
SOURCES = ("asof.py", "dataset.py", "evaluate.py")


def _hash_sources():
    h = hashlib.sha256()
    for name in SOURCES:
        h.update((Path(__file__).parent / name).read_bytes())
    return h.hexdigest()[:12]


# Computed once, at import. A long build must be keyed by the code the process
# actually LOADED, not by whatever is on disk when it happens to finish: editing
# a feature module mid-run would otherwise write rows built by the old code under
# the new code's key - a poisoned cache that looks current.
FINGERPRINT = _hash_sources()


def fingerprint():
    return FINGERPRINT


def cached_split(con, train_years, test_years, horizon=3, verbose=False, **kw):
    """load_split with a disk cache. Same signature, same return value."""
    from .evaluate import load_split

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tag = "_".join(f"{k}={v}" for k, v in sorted(kw.items()) if v)
    key = (f"{min(train_years)}-{max(train_years)}_{min(test_years)}-{max(test_years)}"
           f"_h{horizon}_{tag}_{fingerprint()}")
    p = CACHE_DIR / f"split_{key}.pkl"
    if p.exists():
        with io.open(p, "rb") as f:
            return pickle.load(f)
    out = load_split(con, train_years, test_years, horizon, verbose=verbose, **kw)
    with io.open(p, "wb") as f:
        pickle.dump(out, f, protocol=4)
    return out


if __name__ == "__main__":
    print(f"fingerprint {fingerprint()}  dir {CACHE_DIR}")
    for p in sorted(CACHE_DIR.glob("split_*.pkl")):
        print(f"  {p.name}  {p.stat().st_size/1e6:.1f}MB")
