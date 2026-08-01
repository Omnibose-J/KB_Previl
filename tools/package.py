"""제출물 3종을 만들고, 심사자와 같은 조건으로 리허설한다.

    python -m tools.package              # 빌드만
    python -m tools.package --rehearse   # 빈 폴더에 풀고 새 venv 로 실제 기동
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from .audit import ship_paths, shipped_text
from .manifest import ROOT, SHIP_FILES, SHIP_TREES, TREE_EXCLUDE, ZIP_ROOT

STRIPPED = {".py", ".ts", ".tsx"}

OUT = ROOT / "SUBMISSION"
SERVICE_ZIP = OUT / "KB_Previl_service.zip"
DB_ZIP = OUT / "KB_Previl_db.zip"
DB_FILE = ROOT / "kb-demo.db"
REHEARSAL_PORT = 8123


def service_items():
    """(원본, zip 안 경로) 목록."""
    py, _ = ship_paths()
    items = [(p, p.relative_to(ROOT).as_posix()) for p in py]
    for src, arc in SHIP_FILES:
        p = ROOT / src
        if not p.is_file():
            raise SystemExit(f"{src} 없음 — 빌드 중단")
        items.append((p, arc))
    for src, arc in SHIP_TREES:
        base = ROOT / src
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(base)
            if not p.is_file() or TREE_EXCLUDE & set(rel.parts):
                continue
            items.append((p, f"{arc}/{rel.as_posix()}"))
    if not any(a == "web/index.html" for _, a in items):
        raise SystemExit("web/index.html 없음 — `npx vite build` 를 먼저 돌릴 것")
    seen, out = set(), []
    for src, arc in items:
        if arc not in seen:
            seen.add(arc)
            out.append((src, f"{ZIP_ROOT}/{arc}"))
    return out


def _clear(path):
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        raise SystemExit(
            f"{path.name} 을 다른 프로그램이 열어 두고 있어 다시 만들 수 없다.\n"
            "  압축 프로그램이나 탐색기 미리보기 창을 닫고 다시 실행할 것.")


def build_service():
    items = service_items()
    OUT.mkdir(parents=True, exist_ok=True)
    _clear(SERVICE_ZIP)
    with zipfile.ZipFile(SERVICE_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for src, arc in items:
            if src.suffix in STRIPPED and not arc.startswith(f"{ZIP_ROOT}/web/"):
                z.writestr(arc, shipped_text(src))
            else:
                z.write(src, arc)
    mb = SERVICE_ZIP.stat().st_size / 1e6
    print(f"① {SERVICE_ZIP.name:<26} {mb:>6.1f} MB · {len(items):,}개 파일")
    top = {}
    for _, arc in items:
        rest = arc[len(ZIP_ROOT) + 1:]
        key = rest.split("/")[0] if "/" in rest else "(루트)"
        top[key] = top.get(key, 0) + 1
    for k, v in sorted(top.items(), key=lambda x: -x[1]):
        print(f"     {k:<22} {v:>5}")
    return SERVICE_ZIP


def build_db():
    if not DB_FILE.is_file():
        raise SystemExit(f"{DB_FILE.name} 없음 — `python -m service.demo_db` 로 만든다")
    OUT.mkdir(parents=True, exist_ok=True)
    _clear(DB_ZIP)
    with zipfile.ZipFile(DB_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(DB_FILE, DB_FILE.name)
    raw = DB_FILE.stat().st_size / 1e6
    mb = DB_ZIP.stat().st_size / 1e6
    print(f"② {DB_ZIP.name:<26} {mb:>6.1f} MB  (원본 {raw:,.0f} MB)")
    return DB_ZIP


def stage_env():
    src = ROOT / ".env"
    if not src.is_file():
        print("③ .env                        없음 — 직접 넣어야 한다")
        return None
    dst = OUT / ".env"
    shutil.copy2(src, dst)
    print(f"③ {dst.name:<26} {dst.stat().st_size:>6,} B  (키 파일 — zip 에 없음)")
    return dst


def _get(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, "", b""
    except (urllib.error.URLError, OSError, TimeoutError):
        return None, "", b""


def _wait(url, proc, limit=420):
    t0 = time.time()
    while time.time() - t0 < limit:
        if proc.poll() is not None:
            return False
        if _get(url, timeout=3)[0] == 200:
            return True
        time.sleep(2)
    return False


def _stop_tree(proc):
    """run.py 는 uvicorn 을 또 낳는다. 부모만 죽이면 손자가 DB 를 붙든 채 남는다."""
    if not proc or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def rehearse():
    """service.zip + db.zip 을 빈 폴더에 풀고 run.py 하나로 띄워 본다."""
    outer = Path(tempfile.mkdtemp(prefix="kb-rehearsal-"))
    tmp = outer / ZIP_ROOT
    proc = None
    try:
        print(f"\n[리허설] {outer}")
        with zipfile.ZipFile(SERVICE_ZIP) as f:
            f.extractall(outer)
        with zipfile.ZipFile(DB_ZIP) as f:
            f.extractall(tmp)
        for must in ("README.md", "run.py", "requirements.txt", "kb-demo.db",
                     "service/app.py", "web/index.html", "verify.ipynb"):
            ok = (tmp / must).is_file()
            print(f"  [{'PASS' if ok else 'FAIL'}] {must}")
            if not ok:
                return 1

        base = f"http://127.0.0.1:{REHEARSAL_PORT}"
        env = dict(os.environ, PYTHONPATH="", PYTHONIOENCODING="utf-8")
        env.pop("KB_DB", None)
        print("  새 venv 생성 + 의존성 설치 — 몇 분 걸린다")
        proc = subprocess.Popen(
            [sys.executable, "run.py", "--no-browser",
             "--port", str(REHEARSAL_PORT)],
            cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        if not _wait(f"{base}/api/meta", proc):
            print("  [FAIL] 기동 실패")
            if proc.poll() is None:
                proc.terminate()
            print((proc.stdout.read() or "")[-2000:])
            return 1

        status, _, body = _get(f"{base}/api/meta")
        import json
        meta = json.loads(body)
        uptae = (meta.get("uptae") or ["한식"])[0]
        uptae = uptae.get("name", uptae) if isinstance(uptae, dict) else uptae
        q = urllib.parse.quote(uptae)
        rec_s, _, rec_b = _get(f"{base}/api/recommend?uptae={q}&limit=3")
        items = len((json.loads(rec_b) if rec_s == 200 else {}).get("items") or [])
        ui_s, _, ui_b = _get(base + "/")
        gr_s, _, gr_b = _get(f"{base}/api/grids?uptae={q}"
                             "&bbox=127.024,37.494,127.032,37.501")
        cells = len((json.loads(gr_b) if gr_s == 200 else {}).get("items") or [])

        import re
        wanted, seen, missing, wrong = set(), set(), [], []
        for js in (tmp / "web" / "assets").glob("*.js"):
            wanted |= set(re.findall(r'"([\w.-]+\.mjs)"',
                                     js.read_text("utf-8", "ignore")))
        while wanted:
            name = wanted.pop()
            if name in seen or name.endswith("-dev.mjs"):
                continue
            seen.add(name)
            s, ctype, b = _get(f"{base}/assets/{name}")
            if s != 200:
                missing.append(f"{name}:{s}")
                continue
            if "javascript" not in ctype and "ecmascript" not in ctype:
                wrong.append(f"{name}:{ctype.split(';')[0]}")
            wanted |= set(re.findall(r'from\s*["\']\./([\w.-]+\.mjs)["\']',
                                     b.decode("utf-8", "ignore")))

        boot_ok = status == 200 and rec_s == 200 and items > 0 and ui_s == 200
        print(f"  [{'PASS' if boot_ok else 'FAIL'}] 부팅 — /api/meta {status} · "
              f"/api/recommend {rec_s} ({items}건) · UI {ui_s} ({len(ui_b):,} bytes)")
        grid_ok = gr_s == 200 and cells > 0
        print(f"  [{'PASS' if grid_ok else 'FAIL'}] 지도 데이터 — {gr_s} · {cells}칸")
        map_ok = bool(seen) and not missing and not wrong
        print(f"  [{'PASS' if map_ok else 'FAIL'}] 지도 워커 — {len(seen)}개 서빙")
        for label, bad in (("404·오류", missing), ("MIME 오류", wrong)):
            if bad:
                print(f"      {label}: {', '.join(bad)}")

        ok = boot_ok and grid_ok and map_ok
        print("\n리허설 통과 — 이 3종은 제출 가능하다" if ok else "\n리허설 실패")
        return 0 if ok else 1
    finally:
        _stop_tree(proc)
        shutil.rmtree(outer, ignore_errors=True)


def main():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="제출물 3종 빌드 + 리허설")
    ap.add_argument("--rehearse", action="store_true")
    a = ap.parse_args()
    print(f"제출물 → {OUT}")
    build_service()
    build_db()
    stage_env()
    if not a.rehearse:
        return 0
    return rehearse()


if __name__ == "__main__":
    sys.exit(main())
