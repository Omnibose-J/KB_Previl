"""Build the prototype zip for submission, and rehearse unpacking it.

Contract: docs/submission.md §1. Two rules shape this file.

**Allowlist, never denylist.** The archive is assembled from an explicit include
list. A denylist that forgets one pattern ships `.env`; an allowlist that forgets
one pattern ships a demo that fails loudly at build time. Only one of those two
failure modes is recoverable.

**Rehearse before submitting.** `--rehearse` unpacks the archive into a scratch
directory and boots the API *from there* with nothing else on the path, which is
the only way to catch a file that exists in the working tree and not in the zip.
submission.md forbids submitting without it.

Usage:
    python scripts/package_submission.py                 # build
    python scripts/package_submission.py --rehearse      # build + unpack + boot
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "submission" / "KB_Previl_prototype.zip"

# (source, arcname). Directories are walked with the glob that follows.
FILES = [
    (ROOT / "docs" / "제출-README.md", "README.md"),   # judge-facing, not the dev README
    (ROOT / "requirements.txt", "requirements.txt"),
    (ROOT / "requirements-full.txt", "requirements-full.txt"),
    (ROOT / ".env.example", ".env.example"),
    (ROOT / "kb-demo.db", "kb-demo.db"),
]

TREES = [
    ("service", "**/*.py"),
    ("model", "**/*.py"),
    ("pipeline", "**/*.py"),
    ("probe", "**/*.py"),
    ("scripts", "**/*.py"),
    ("lanes", "**/*.md"),
    ("docs", "**/*.md"),
    ("docs/figures", "**/*.png"),
    ("frontend/app/dist", "**/*"),
    ("frontend/app/src", "**/*"),
    ("frontend/design", "**/*.md"),
]

# Files matching these are dropped even when a tree glob picks them up.
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", ".vite"}

# Nothing matching these may ever appear in the archive. Checked after the fact:
# a bug in the include list is a bug, shipping a key is an incident.
#
# Matched on path STRUCTURE, not substrings. A substring rule rejects
# `.env.example` (which must ship) and `model/cache.py` (which is source), and a
# check that cries wolf gets disabled by the next person in a hurry.
FORBIDDEN_NAMES = {".env", ".env.bak", "kb.db", "kb.db-shm", "kb.db-wal"}
FORBIDDEN_PREFIX = ("kb-w5", "kb-baseline", "kb-osm", "kb-pre-coldswap")
FORBIDDEN_DIRS = {"cache", "node_modules", "__pycache__", ".git", ".venv"}


def leaks(arc):
    parts = arc.split("/")
    name = parts[-1]
    return (name in FORBIDDEN_NAMES
            or name.startswith(FORBIDDEN_PREFIX)
            or bool(FORBIDDEN_DIRS & set(parts[:-1])))


def collect():
    items = list(FILES)
    for rel, pattern in TREES:
        base = ROOT / rel
        if not base.is_dir():
            raise RuntimeError(f"{rel} 없음 — 빌드 중단")
        for p in sorted(base.glob(pattern)):
            if not p.is_file() or SKIP_PARTS & set(p.parts):
                continue
            items.append((p, str(p.relative_to(ROOT)).replace("\\", "/")))
    # dist must carry an entry point or the one-command demo silently serves 404
    if not any(a.endswith("dist/index.html") for _, a in items):
        raise RuntimeError("frontend/app/dist/index.html 없음 — `npx vite build` 를 먼저 돌릴 것")
    seen, out = set(), []
    for src, arc in items:
        if arc not in seen:
            seen.add(arc)
            out.append((src, arc))
    return out


def build(verbose=True):
    items = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    t0 = time.time()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for src, arc in items:
            z.write(src, arc)

    names = zipfile.ZipFile(OUT).namelist()
    leaked = [n for n in names if leaks(n)]
    if leaked:
        OUT.unlink()
        raise RuntimeError(f"금지 항목이 담겼다 — zip 삭제함: {leaked[:5]}")

    if verbose:
        mb = OUT.stat().st_size / 1e6
        by_top = {}
        for n in names:
            by_top[n.split("/")[0]] = by_top.get(n.split("/")[0], 0) + 1
        print(f"{OUT.relative_to(ROOT)}  {mb:.1f} MB · {len(names):,}개 파일 "
              f"({time.time()-t0:.0f}초)")
        for k, v in sorted(by_top.items(), key=lambda x: -x[1])[:10]:
            print(f"  {k:<28} {v:>5}")
        print(f"  금지 항목(.env·kb.db·캐시) 검사: 통과")
    return OUT


# Runs inside the unpacked zip. Beyond status codes it checks that the map's
# Web Worker is actually loadable, because a 200 on `/` says nothing about it.
#
# Three separate bugs shipped past a status-code-only rehearsal (커밋 30a8f34):
# the worker file was never emitted, then it was emitted without the chunk it
# imports, then it was served as text/plain. Each one leaves the map showing
# raster tiles and zero grade cells — the whole screen — with no console error.
#
# The worker filename is NOT hardcoded. It is read out of the built bundle, so
# a MapLibre upgrade that renames or splits the worker is followed, not missed.
BOOT_SCRIPT = r"""
import json, re, sys, pathlib
from fastapi.testclient import TestClient
from service.app import app

c = TestClient(app)
m = c.get('/api/meta')
u = (m.json().get('uptae') or ['한식'])[0]
u = u.get('name', u) if isinstance(u, dict) else u
r = c.get('/api/recommend', params={'uptae': u, 'limit': 3})
h = c.get('/')

# 지도가 실제로 그릴 데이터가 있는가 — /api/grids 는 격자 레이어의 유일한 원천이다.
g = c.get('/api/grids', params={'uptae': u, 'bbox': '127.024,37.494,127.032,37.501'})
cells = len((g.json() or {}).get('items') or []) if g.status_code == 200 else 0

# 번들이 런타임에 부르는 .mjs 를 전부 모아 실제로 서빙되는지 확인한다.
dist = pathlib.Path('frontend/app/dist')
wanted, missing, wrong_type = set(), [], []
for js in dist.glob('assets/*.js'):
    wanted |= set(re.findall(r'"([\w.-]+\.mjs)"', js.read_text('utf-8', 'ignore')))
seen = set()
while wanted:
    name = wanted.pop()
    if name in seen or name.endswith('-dev.mjs'):   # dev 워커는 빌드본이 안 쓴다
        continue
    seen.add(name)
    resp = c.get(f'/assets/{name}')
    if resp.status_code != 200:
        missing.append(f'{name}:{resp.status_code}')
        continue
    ctype = (resp.headers.get('content-type') or '').split(';')[0]
    if 'javascript' not in ctype and 'ecmascript' not in ctype:
        wrong_type.append(f'{name}:{ctype}')
    # 그 파일이 또 상대 import 를 하면 그것도 서빙돼야 한다
    wanted |= set(re.findall(r'from\s*["\']\./([\w.-]+\.mjs)["\']',
                             resp.text))

print(json.dumps({
    'meta': m.status_code, 'recommend': r.status_code,
    'items': len((r.json() or {}).get('items') or []),
    'ui': h.status_code, 'ui_bytes': len(h.content),
    'grids': g.status_code, 'cells': cells,
    'workers': sorted(seen), 'missing': missing, 'wrong_type': wrong_type,
}))
"""


def rehearse(zip_path):
    """Unpack into a scratch dir and boot the API there, as a judge would."""
    tmp = Path(tempfile.mkdtemp(prefix="kb-rehearsal-"))
    try:
        print(f"\n[리허설] {tmp}")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        for must in ("README.md", "requirements.txt", "kb-demo.db",
                     "service/app.py", "frontend/app/dist/index.html"):
            ok = (tmp / must).is_file()
            print(f"  [{'PASS' if ok else 'FAIL'}] {must}")
            if not ok:
                return 1

        # Boot from the unpacked copy with cwd there and ROOT off sys.path, so a
        # file that only exists in the working tree cannot rescue the run.
        script = BOOT_SCRIPT
        # KB_DB 를 넣지 않는다. 심사자는 환경변수 없이 실행하므로, 여기서
        # 지정해 주면 게이트가 심사자와 다른 경로를 검사하게 된다.
        env = dict(os.environ, PYTHONPATH="", PYTHONIOENCODING="utf-8")
        env.pop("KB_DB", None)
        p = subprocess.run([sys.executable, "-c", script], cwd=tmp, env=env,
                           capture_output=True, text=True, timeout=300)
        line = [l for l in p.stdout.splitlines() if l.startswith("{")]
        if p.returncode or not line:
            print(f"  [FAIL] 부팅 실패 (exit {p.returncode})")
            print((p.stderr or p.stdout)[-1200:])
            return 1
        res = json.loads(line[-1])
        boot_ok = (res["meta"] == 200 and res["recommend"] == 200
                   and res["items"] > 0 and res["ui"] == 200
                   and res["ui_bytes"] > 0)
        print(f"  [{'PASS' if boot_ok else 'FAIL'}] 부팅 — /api/meta {res['meta']} · "
              f"/api/recommend {res['recommend']} ({res['items']}건) · "
              f"UI {res['ui']} ({res['ui_bytes']:,} bytes)")

        grid_ok = res["grids"] == 200 and res["cells"] > 0
        print(f"  [{'PASS' if grid_ok else 'FAIL'}] 지도 데이터 — /api/grids "
              f"{res['grids']} · 격자 {res['cells']}칸")

        # 워커를 하나도 못 찾았다면 그것 자체가 실패다. «검사할 게 없어서 통과»
        # 는 이 검사가 막으려는 상태와 화면에서 구분되지 않는다.
        map_ok = (bool(res["workers"]) and not res["missing"]
                  and not res["wrong_type"])
        print(f"  [{'PASS' if map_ok else 'FAIL'}] 지도 워커 — "
              f"{len(res['workers'])}개 서빙 ({', '.join(res['workers']) or '없음'})")
        for label, items in (("404·오류", res["missing"]),
                             ("MIME 오류", res["wrong_type"])):
            if items:
                print(f"      {label}: {', '.join(items)}")

        ok = boot_ok and grid_ok and map_ok
        print("\n리허설 통과 — 이 zip 은 제출 가능하다" if ok else "\n리허설 실패")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="제출 zip 패키징 + 리허설")
    ap.add_argument("--rehearse", action="store_true",
                    help="빌드 후 임시 폴더에 풀어 실제로 띄워 본다")
    a = ap.parse_args()
    z = build()
    return rehearse(z) if a.rehearse else 0


if __name__ == "__main__":
    sys.exit(main())
