"""KB Previl 실행기 — 셋업, DB 확인, 백필, 서버 기동."""
import argparse
import hashlib
import os
import subprocess
import sys
import threading
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
GUARD = "KB_PREVIL_VENV"
DB_NAMES = ("kb.db", "kb-demo.db")
DEFAULT_PORT = 8000


def use_utf8():
    """한글 안내문이 리다이렉트나 비한글 로캘에서 죽지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def venv_python():
    tail = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return VENV / tail


def ensure_venv(full=False):
    """가상환경과 의존성을 준비하고 그 파이썬 경로를 돌려준다."""
    py = venv_python()
    if not py.is_file():
        print(f"[1/4] 가상환경 생성 — {VENV.name}")
        venv.EnvBuilder(with_pip=True).create(VENV)
    else:
        print("[1/4] 가상환경 있음")

    req = ROOT / ("requirements-full.txt" if full else "requirements.txt")
    # 내용 해시로 찍는다. mtime 은 내용이 바뀌어도 같을 수 있다. 스탬프는
    # 목록마다 따로 둔다 — 하나면 최소/전체를 오갈 때마다 서로 덮어 다시 깐다.
    stamp = VENV / f"deps-{req.stem}.stamp"
    digest = hashlib.sha256(req.read_bytes()).hexdigest()[:16]
    if stamp.is_file() and stamp.read_text(encoding="utf-8") == digest:
        print(f"[2/4] 의존성 설치됨 — {req.name}")
        return py
    print(f"[2/4] 의존성 설치 — {req.name}, 처음이면 1~2분 걸린다")
    subprocess.check_call([str(py), "-m", "pip", "install", "-q",
                           "--disable-pip-version-check", "-r", str(req)])
    stamp.write_text(digest, encoding="utf-8")
    return py


def db_override():
    return os.environ.get("KB_DB")


def find_db():
    """서비스가 여는 것과 같은 규칙: KB_DB > kb.db > kb-demo.db.

    여기서 kb-demo.db 를 확인해 놓고 uvicorn 이 물려받은 KB_DB 로 다른 파일을
    열면, 화면은 멀쩡한 채 다른 데이터가 서빙된다. 고르는 곳은 하나여야 한다.
    """
    override = db_override()
    if override:
        p = Path(override).expanduser().resolve()
        return p if p.is_file() else None
    for name in DB_NAMES:
        p = ROOT / name
        if p.is_file():
            return p
    return None


def db_target():
    """백필이 만들 DB. 서비스가 그 다음에 열 파일과 같은 경로여야 한다."""
    override = db_override()
    return Path(override).expanduser().resolve() if override else ROOT / DB_NAMES[0]


def child_env(db):
    """고른 DB 를 자식에게 명시적으로 넘긴다. 물려받은 값에 맡기지 않는다."""
    resolved = Path(db).expanduser().resolve()
    return dict(os.environ, PYTHONIOENCODING="utf-8", KB_DB=str(resolved))


def explain_missing_db():
    print("\n[3/4] 데이터베이스 없음")
    override = db_override()
    if override:
        print(f"  KB_DB 가 가리키는 파일이 없다: {override}")
        print("  그 경로에 DB 를 두거나, KB_DB 를 지우고 다시 실행한다")
        return
    print(f"  이 폴더에 {' 또는 '.join(DB_NAMES)} 가 있어야 한다: {ROOT}")
    print("  해결 A — 함께 제출된 DB zip 을 이 폴더에 풀어 kb-demo.db 를 놓는다")
    print("  해결 B — .env 를 이 폴더에 두고 `python run.py --backfill` 로 직접 만든다")
    print("           원천 API 로 다시 수집하므로 하루 이상 걸린다")


def backfill(py, dry_run):
    """.env 의 키로 빈 DB에서 서빙 가능한 DB까지 만든다."""
    if not (ROOT / ".env").is_file():
        print(f"[FAIL] .env 없음 — {ROOT / '.env'} 에 API 키 파일이 필요하다")
        return 1
    env = child_env(db_target())
    for step, why in (("--preflight", "사전 점검"), ("--plan", "계획 확인")):
        rc = subprocess.call([str(py), "-m", "pipeline.bootstrap", step],
                             cwd=ROOT, env=env)
        if rc:
            # 계획 단계가 실패했는데 수집을 시작하면 하루를 버리고 나서 안다.
            print(f"[FAIL] {why} 실패 — 위 항목을 고친 뒤 다시 실행한다")
            return rc
    if dry_run:
        print("\n--dry-run — 여기까지만 하고 수집을 시작하지 않았다")
        return 0
    print("\n백필 시작 — 서울 열린데이터 일일 한도 때문에 하루 이상 걸린다.")
    print("중간에 끊기면 같은 명령을 다시 치면 이어서 받는다.")
    return subprocess.call([str(py), "-m", "pipeline.bootstrap"], cwd=ROOT, env=env)


def port_in_use(port):
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def port_owner(port):
    """(pid, cmdline) of the process LISTENING on the port, else (None, "")."""
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                                 capture_output=True, text=True).stdout
            for line in out.splitlines():
                parts = line.split()
                if (len(parts) >= 5 and parts[3] == "LISTENING"
                        and parts[1].rsplit(":", 1)[-1] == str(port)):
                    pid = int(parts[4])
                    cmd = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                        capture_output=True, text=True).stdout.strip()
                    return pid, cmd
        else:
            out = subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
                                 capture_output=True, text=True).stdout.strip()
            if out:
                pid = int(out.splitlines()[0])
                cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                     capture_output=True, text=True).stdout.strip()
                return pid, cmd
    except (OSError, ValueError):
        pass
    return None, ""


def reclaim_port(port, url):
    """더블클릭을 두 번 하면 bind 오류가 «Python 미설치?» 안내로 이어져 원인을
    거꾸로 말하게 된다(2026-08-03 실사고). 우리 서버로 확인된 프로세스만 끄고
    이어서 새로 띄운다 — 남의 프로그램이면 절대 끄지 않고 사정을 말한다."""
    import time

    pid, cmd = port_owner(port)
    if pid is None or "uvicorn" not in cmd or "service.app" not in cmd:
        print(f"{url} 을 다른 프로그램이 쓰고 있어요. 그 프로그램을 닫거나,")
        print(f"    python run.py --port {port + 1}")
        print("처럼 다른 포트로 띄워 주세요.")
        return False
    print(f"이전에 띄운 서버(PID {pid})가 아직 켜져 있어요 — 끄고 새로 시작합니다.")
    os.kill(pid, 15)
    for _ in range(20):
        if not port_in_use(port):
            return True
        time.sleep(0.25)
    print("이전 서버가 끝나지 않아요 — 그 창을 직접 닫고(Ctrl+C) 다시 실행해 주세요.")
    return False


def serve(py, port, open_browser, db):
    url = f"http://127.0.0.1:{port}"
    if port_in_use(port) and not reclaim_port(port, url):
        return 1
    print(f"[4/4] 서버 기동 — {url}  (멈추려면 Ctrl+C)")
    if open_browser:
        threading.Timer(2.0, webbrowser.open, args=(url,)).start()
    return subprocess.call(
        [str(py), "-m", "uvicorn", "service.app:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=child_env(db))


def main():
    use_utf8()
    ap = argparse.ArgumentParser(description="KB Previl — 셋업하고 서비스를 띄운다")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--backfill", action="store_true",
                    help="DB 가 있어도 원천에서 다시 만든다")
    ap.add_argument("--backfill-only", action="store_true",
                    help="백필만 하고 서버를 띄우지 않는다")
    ap.add_argument("--dry-run", action="store_true",
                    help="--backfill-only 와 함께 — 점검과 계획만 출력")
    a = ap.parse_args()

    have_db = find_db() is not None
    have_env = (ROOT / ".env").is_file()
    asked = a.backfill or a.backfill_only
    if not have_db and not have_env and not asked:
        explain_missing_db()
        return 1

    py = ensure_venv(full=asked or not have_db)
    if not os.environ.get(GUARD) and Path(sys.executable) != py:
        os.environ[GUARD] = "1"
        return subprocess.call([str(py), str(ROOT / "run.py"), *sys.argv[1:]])

    if asked or not have_db:
        rc = backfill(py, a.dry_run)
        if rc or a.backfill_only or a.dry_run:
            return rc
    db = find_db()
    if db is None:
        explain_missing_db()
        return 1
    print(f"[3/4] 데이터베이스 — {db.name} ({db.stat().st_size / 1024**2:,.0f} MB)")
    return serve(py, a.port, not a.no_browser, db)


if __name__ == "__main__":
    sys.exit(main())
