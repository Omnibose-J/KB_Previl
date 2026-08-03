"""제출용 zip 하나를 만들고, 심사자와 같은 조건으로 리허설한다.

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

from .audit import gate_zip, is_stripped, ship_items, ship_paths, shipped_text
from .manifest import ROOT, ZIP_ROOT, submission_env

OUT = ROOT / "SUBMISSION"
SUBMISSION_ZIP = OUT / "KB_Previl.zip"
DB_FILE = ROOT / "kb-demo.db"
REHEARSAL_PORT = 8123
LEGACY_OUTPUTS = (
    OUT / "KB_Previl_all.zip",
    OUT / "KB_Previl_service.zip",
    OUT / "KB_Previl_db.zip",
    OUT / ".env",
)
TEMP_ZIP = OUT / ".KB_Previl.zip.tmp"


def service_items():
    """(원본, zip 안 경로) 목록. 게이트와 같은 함수를 쓴다."""
    items = ship_items()
    if not any(a == f"{ZIP_ROOT}/web/index.html" for _, a in items):
        raise SystemExit("web/index.html 없음 — `npx vite build` 를 먼저 돌릴 것")
    return items


def _clear(path):
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        raise SystemExit(
            f"{path.name} 을 다른 프로그램이 열어 두고 있어 다시 만들 수 없다.\n"
            "  압축 프로그램이나 탐색기 미리보기 창을 닫고 다시 실행할 것.")


def _drop_stale(*paths):
    """이번에 만들지 않는 형태의 산출물은 지운다. 낡은 zip 을 잘못 내지 않게."""
    for path in paths:
        if not path.exists():
            continue
        try:
            path.unlink()
            print(f"   낡은 산출물 삭제 — {path.name}")
        except PermissionError as exc:
            raise SystemExit(
                f"낡은 산출물 {path.name} 삭제 실패 — 압축 프로그램이나 탐색기 "
                "미리보기 창을 닫고 다시 실행할 것") from exc


def build_bundle(env_payload):
    """Write code, database, and the filtered environment into one zip."""
    if not DB_FILE.is_file():
        raise SystemExit(f"{DB_FILE.name} 없음 — `python -m service.demo_db` 로 만든다")
    items = service_items()
    OUT.mkdir(parents=True, exist_ok=True)
    _clear(TEMP_ZIP)
    try:
        with zipfile.ZipFile(TEMP_ZIP, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as z:
            for src, arc in items:
                if is_stripped(src, arc):
                    z.writestr(arc, shipped_text(src))
                else:
                    z.write(src, arc)
            z.write(DB_FILE, f"{ZIP_ROOT}/{DB_FILE.name}")
            z.writestr(f"{ZIP_ROOT}/.env", env_payload)
        TEMP_ZIP.replace(SUBMISSION_ZIP)
    except PermissionError as exc:
        raise SystemExit(
            f"{SUBMISSION_ZIP.name} 교체 실패 — 압축 프로그램이나 탐색기 "
            "미리보기 창을 닫고 다시 실행할 것") from exc
    finally:
        TEMP_ZIP.unlink(missing_ok=True)
    mb = SUBMISSION_ZIP.stat().st_size / 1e6
    print(f"① {SUBMISSION_ZIP.name:<26} {mb:>6.1f} MB · {len(items) + 2:,}개 파일 "
          f"(코드 + DB + .env)")
    return SUBMISSION_ZIP


def stage_env():
    """Return only the secrets read by the shipped product."""
    src = ROOT / ".env"
    if not src.is_file():
        print(f"② .env  FAIL — {src} 없음. 산출물이 완성되지 않았다")
        return None
    py, _ = ship_paths()
    payload, kept, dropped, missing = submission_env(src, py)
    print(f"② previl/.env{'':<15} {len(payload):>6,} B  "
          f"(키 {len(kept)}종 — zip 내부)")
    if dropped:
        print(f"     제외 {len(dropped)}종 — 이 제품이 안 쓰는 키: "
              f"{', '.join(dropped)}")
    for key in missing:
        print(f"     [경고] {key} 가 .env 에 없다 — 백필이 그 단계에서 멈춘다")
    return payload


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
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def rehearse():
    """실제로 낼 zip 을 빈 폴더에 풀고 run.py 하나로 띄워 본다."""
    outer = Path(tempfile.mkdtemp(prefix="kb-rehearsal-"))
    tmp = outer / ZIP_ROOT
    proc = None
    try:
        print(f"\n[리허설] {outer}  ({SUBMISSION_ZIP.name})")
        with zipfile.ZipFile(SUBMISSION_ZIP) as f:
            f.extractall(outer)
        for must in ("README.md", "run.py", "run.bat", "requirements.txt",
                     "kb-demo.db", ".env", "service/app.py", "web/index.html",
                     "service/data/franchise_costs.json", "verify.ipynb"):
            ok = (tmp / must).is_file()
            print(f"  [{'PASS' if ok else 'FAIL'}] {must}")
            if not ok:
                return 1

        base = f"http://127.0.0.1:{REHEARSAL_PORT}"
        env = dict(os.environ, PYTHONPATH="", PYTHONIOENCODING="utf-8")
        env.pop("KB_DB", None)
        print("  새 venv 생성 + 의존성 설치 — 몇 분 걸린다")
        # 심사위원이 실제로 밟는 입구를 그대로 밟는다 — Windows 는 run.bat,
        # 그 외는 run.py. stdin 을 닫아 실패 시 배치의 pause 가 매달리지 않게.
        # 경로를 명시한다 — bare 이름은 cmd 가 CWD 를 안 뒤지는 환경에서 죽고,
        # 더블클릭(탐색기)도 어차피 전체 경로로 실행한다.
        launch = (
            ["cmd", "/c", str(tmp / "run.bat"),
             "--no-browser", "--port", str(REHEARSAL_PORT)]
            if os.name == "nt"
            else [sys.executable, "run.py", "--no-browser",
                  "--port", str(REHEARSAL_PORT)]
        )
        proc = subprocess.Popen(
            launch,
            cwd=tmp, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            start_new_session=(os.name != "nt"))
        if not _wait(f"{base}/api/meta", proc):
            print("  [FAIL] 기동 실패")
            if proc.poll() is None:
                proc.terminate()
            print((proc.stdout.read() or "")[-2000:])
            return 1

        status, _, body = _get(f"{base}/api/meta")
        import json
        meta = json.loads(body)
        # 기본값으로 때우지 않는다 — /api/meta 가 업종을 못 내는 것 자체가 파손이고,
        # 대체값을 쓰면 그 파손이 아래 검사에서 초록으로 덮인다.
        uptae_list = meta.get("uptae") or []
        if not uptae_list:
            print("  [FAIL] /api/meta 에 업종 목록이 없다")
            return 1
        uptae = uptae_list[0]
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
        print(f"\n리허설 통과 — {SUBMISSION_ZIP.name} 제출 가능" if ok else "\n리허설 실패")
        return 0 if ok else 1
    finally:
        _stop_tree(proc)
        shutil.rmtree(outer, ignore_errors=True)


def main():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="제출물 빌드 + 리허설")
    ap.add_argument("--rehearse", action="store_true")
    a = ap.parse_args()
    print(f"제출물 → {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)
    env_payload = stage_env()
    if env_payload is None:
        _clear(SUBMISSION_ZIP)
        return 1
    build_bundle(env_payload)
    _drop_stale(*LEGACY_OUTPUTS)
    if not a.rehearse:
        return 0
    if gate_zip(False, SUBMISSION_ZIP):
        print("\n리허설 중단 — zip 내용 검사 실패")
        return 1
    return rehearse()


if __name__ == "__main__":
    sys.exit(main())
