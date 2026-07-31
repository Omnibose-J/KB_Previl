"""Extract the serving subset of kb.db into a shippable demo database.

Contract: docs/submission.md §1. The prototype zip cannot carry kb.db (229MB)
or pipeline/cache/ (807MB), and should not: a judge needs the app to run, not
the pipeline to be reproducible from the archive. What the app needs is exactly
the tables service/ reads.

The table list is derived, not guessed. `--audit` re-derives it by scanning
service/*.py for FROM/JOIN/INTO/UPDATE against the live schema and reports any
drift against TABLES below, so a new query in the service cannot silently ship a
demo database that 404s at the judge's desk.

Deliberately excluded, and why it is safe: addr_tenancy (535k), shop_concept
(477k) and store (139k) are pipeline/model inputs with no serving reader. Every
number the UI shows comes from grid_score / score_meta / the grid_* feature
tables, which are all included.

Usage:
    python -m service.demo_db --out kb-demo.db     # build
    python -m service.demo_db --audit              # check the list is current
    python -m service.demo_db --verify kb-demo.db  # boot the API against it
"""
import argparse
import ast
import re
import sqlite3
import sys
from pathlib import Path

from pipeline.config import DB_PATH, ROOT

# Serving dependencies, largest first. Row counts are informational only - the
# build copies whatever is there.
TABLES = [
    "licence",            # 535,715  건물 기록 (S4 «이 자리의 건물 이력»)
    "grid_score",         # 241,776  등급 — 제품의 중심
    "succession_score",   # 241,776  M2 승계확률
    "grid_score_prev",    # 241,404  직전 점수 (변화 표시)
    "grid_concept",       # 157,862  «주변에 많은 가게»
    "licence_rest",       # 146,184  휴게음식점 (까페 경쟁 수)
    "grid",               #  23,573  격자 좌표·상권 매핑
    "grid_feature",       #  23,573  격자 피처
    "grid_access",        #  23,573  지하철 접근성
    "grid_sgis",          #  23,553  배후 인구·행정동명
    "trdar_store",        #  12,204  상권 점포 수
    "trdar_sales",        #   6,573  상권 추정매출
    "trdar_party",        #           trade-area visitor party labels
    "cohort_survival",    #      44  개업연도별 생존율 (랜딩 추이 그래프)
    "score_meta",         #      41  헤드라인·곡선·밴드
    "score_run",          #       2  적재 이력
]

_SQL_REF = re.compile(r"(?i)\b(?:from|join|into|update)\s+([a-z_][a-z0-9_]*)")
_NON_TABLE_TOKENS = {"sqlite_master"}


def _ro_uri(path):
    """Read-only SQLite URI. `as_uri()` is required on Windows - a raw path puts
    backslashes in the URI, and ATTACH then looks for a file literally named
    `file:C:\\...?mode=ro`."""
    return Path(path).resolve().as_uri() + "?mode=ro"


def live_tables(con):
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def referenced_tables(con):
    """Tables that runtime service code queries, whether or not they exist."""
    strings = []
    for path in sorted((ROOT / "service").glob("*.py")):
        if path.name == "demo_db.py" or path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = {
            ast.get_docstring(node, clean=False)
            for node in ast.walk(tree)
            if isinstance(node, (
                ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        strings.extend(
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value not in docstrings
        )
    names = {
        match.lower()
        for string in strings
        for match in _SQL_REF.findall(string)
    }
    return names - _NON_TABLE_TOKENS


def audit(src_path):
    con = sqlite3.connect(_ro_uri(src_path), uri=True)
    try:
        found, declared = referenced_tables(con), set(TABLES)
        live = live_tables(con)
        missing = sorted((found & live) - declared)
        unloaded = sorted(found - live - declared)
        extra = sorted(declared - found)        # shipped but unused -> dead weight
        absent = sorted(declared - live)
        print(f"선언 {len(declared)}개 · 코드 참조 {len(found)}개")
        if unloaded:
            for table in unloaded:
                print(f"  미적재 참조: {table} — 코드가 읽는데 DB에 없다")
        else:
            print("  미적재 참조: 없음")
        for label, items, why in (
                ("누락 (서비스가 읽는데 TABLES 에 없다)", missing, "데모가 404 를 낸다"),
                ("잉여 (TABLES 에 있는데 아무도 안 읽는다)", extra, "용량만 늘린다"),
                ("스키마 부재 (TABLES 에 있는데 DB 에 없다)", absent, "빌드가 실패한다")):
            print(f"  {label}: {', '.join(items) if items else '없음'}"
                  + (f"   -> {why}" if items else ""))
        return 1 if (missing or unloaded or absent) else 0
    finally:
        con.close()


def build(src_path, out_path, verbose=True):
    out = Path(out_path)
    if out.exists():
        out.unlink()                     # VACUUM into a stale file would keep its pages
    src = sqlite3.connect(_ro_uri(src_path), uri=True)
    # uri=True on the DESTINATION too: SQLITE_OPEN_URI is a per-connection
    # flag and ATTACH inherits it, so without this the URI below is taken
    # as a literal filename.
    dst = sqlite3.connect(str(out), uri=True)
    try:
        have = live_tables(src)
        missing = [t for t in TABLES if t not in have]
        if missing:
            raise RuntimeError(f"원본에 없는 테이블: {', '.join(missing)} — "
                               "파이프라인을 먼저 완주할 것")
        dst.execute("PRAGMA journal_mode=OFF")
        dst.execute("ATTACH DATABASE ? AS src", (_ro_uri(src_path),))
        for t in TABLES:
            ddl = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (t,)).fetchone()[0]
            dst.execute(ddl)
            dst.execute(f"INSERT INTO main.{t} SELECT * FROM src.{t}")
            n = dst.execute(f"SELECT COUNT(*) FROM main.{t}").fetchone()[0]
            if verbose:
                print(f"  {t:<20} {n:>9,}행", flush=True)
        # Indexes matter here: /grids scans a viewport and /recommend sorts a
        # whole 업태, both of which fall off a cliff without them.
        for (ddl,) in src.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
                f"AND tbl_name IN ({','.join('?' * len(TABLES))})", TABLES):
            dst.execute(ddl)
        dst.commit()
        dst.execute("DETACH DATABASE src")
        dst.execute("VACUUM")
        dst.commit()
    finally:
        src.close()
        dst.close()
    mb, orig = out.stat().st_size / 1e6, Path(src_path).stat().st_size / 1e6
    print(f"\n{out}  {mb:.1f} MB  (원본 {orig:.0f} MB · {mb/orig*100:.1f}%)")
    return out


def verify(db_path):
    """Boot the real API against the demo DB and exercise the read paths."""
    import os
    os.environ["KB_DB"] = str(db_path)
    for mod in [m for m in list(sys.modules) if m.startswith(("service", "pipeline"))]:
        del sys.modules[mod]                     # pick up the new KB_DB
    from fastapi.testclient import TestClient

    from service.app import app
    c = TestClient(app)
    checks = []

    r = c.get("/api/meta")
    listing = r.json().get("uptae") if r.status_code == 200 else None
    checks.append(("meta", bool(listing), r.status_code))
    # /meta has served 업태 both as bare strings and as objects across revisions;
    # accept either rather than pin the demo check to one shape.
    first = (listing or ["한식"])[0]
    uptae = first.get("name", first) if isinstance(first, dict) else first

    r = c.get("/api/recommend", params={"uptae": uptae, "limit": 5})
    items = r.json().get("items") if r.status_code == 200 else None
    checks.append(("recommend", bool(items), r.status_code))

    if items:
        gid = items[0]["gridId"]
        r = c.get(f"/api/grid/{gid}", params={"uptae": uptae})
        checks.append(("grid detail", r.status_code == 200, r.status_code))
        r = c.get(f"/api/grid/{gid}/buildings")
        checks.append(("buildings", r.status_code == 200, r.status_code))

    ok = True
    for name, passed, code in checks:
        print(f"  [{name:<12}] {'PASS' if passed else 'FAIL'}  HTTP {code}")
        ok &= bool(passed)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="제출용 경량 데모 DB 추출")
    ap.add_argument("--src", default=str(DB_PATH))
    ap.add_argument("--out", default="kb-demo.db")
    ap.add_argument("--audit", action="store_true", help="TABLES 가 코드와 맞는지만 검사")
    ap.add_argument("--verify", metavar="DB", help="이 DB 로 API 를 띄워 읽기 경로 확인")
    a = ap.parse_args()
    if a.audit:
        return audit(a.src)
    if a.verify:
        return verify(a.verify)
    rc = audit(a.src)
    if rc:
        print("\nTABLES 가 코드와 어긋난다 — 고치기 전에는 빌드하지 않는다")
        return rc
    print()
    build(a.src, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
