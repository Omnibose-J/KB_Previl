"""제출물 3종을 다시 만든다. 서비스가 바뀌면 이것만 다시 돌리면 된다.

    python build.py              게이트 -> 프론트 확인 -> 빌드
    python build.py --rehearse   위에 더해 빈 폴더에서 실제로 띄워 본다
    python build.py --check      게이트만
    python build.py --web        프론트를 무조건 다시 빌드
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "frontend" / "app" / "src"
DIST = ROOT / "frontend" / "app" / "dist"
APP = ROOT / "frontend" / "app"


def newest(path, patterns=("*",)):
    best = 0.0
    for pattern in patterns:
        for p in path.rglob(pattern):
            if p.is_file():
                best = max(best, p.stat().st_mtime)
    return best


def build_web(force):
    """src 가 dist 보다 새로우면 다시 빌드한다. 낡은 화면이 나가는 것을 막는다."""
    index = DIST / "index.html"
    stale = force or not index.is_file() or newest(SRC) > index.stat().st_mtime
    if not stale:
        print("[web] 최신 — 다시 빌드하지 않음")
        return 0
    if not (APP / "node_modules").is_dir():
        print("[web] node_modules 없음 — `npm install` 후 다시 실행할 것")
        return 1
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        print("[web] npx 를 찾지 못함 — Node.js 가 필요하다")
        return 1
    print("[web] 화면 다시 빌드")
    return subprocess.call([npx, "vite", "build"], cwd=APP)


def run(argv, title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    return subprocess.call([sys.executable, "-m", *argv], cwd=ROOT)


def main():
    ap = argparse.ArgumentParser(description="제출물 3종 재빌드")
    ap.add_argument("--rehearse", action="store_true")
    ap.add_argument("--check", action="store_true", help="게이트만 실행")
    ap.add_argument("--web", action="store_true", help="프론트 강제 재빌드")
    ap.add_argument("--skip-web", action="store_true")
    a = ap.parse_args()

    if run(["tools.audit"], "1. 게이트"):
        print("\n게이트 실패 — 빌드하지 않았다")
        return 1
    if a.check:
        return 0
    if not a.skip_web and build_web(a.web):
        return 1
    argv = ["tools.package"] + (["--rehearse"] if a.rehearse else [])
    if run(argv, "2. 빌드" + (" + 리허설" if a.rehearse else "")):
        return 1
    zip_path = ROOT / "SUBMISSION" / "KB_Previl_service.zip"
    return run(["tools.audit", "--zip", str(zip_path)], "3. zip 내용 검사")


if __name__ == "__main__":
    sys.exit(main())
