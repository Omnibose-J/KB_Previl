"""제출물을 다시 만든다. 서비스가 바뀌면 이것만 다시 돌리면 된다.

기본은 합본이다 — `KB_Previl_all.zip`(코드 + DB) 과 `.env` 두 개.

    python build.py              게이트 -> 화면 빌드 -> 패키징
    python build.py --rehearse   위에 더해 빈 폴더에서 실제로 띄워 본다
    python build.py --split      코드 zip 과 DB zip 을 나누어 낸다
    python build.py --check      게이트만
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "frontend" / "app"


def build_web():
    """화면을 무조건 다시 빌드한다.

    «입력이 dist 보다 새로운가» 로 판단하던 것을 버렸다. mtime 은 파일을
    되돌리거나 보존 복사하면 그대로이고, package-lock.json 처럼 빌드에 들어가는
    입력을 목록에서 빠뜨리면 낡은 화면이 조용히 실린다. 제출물 빌드에서 20초를
    아끼려고 그 위험을 질 이유가 없다.
    """
    if not (APP / "node_modules").is_dir():
        print("[web] node_modules 없음 — `npm install` 후 다시 실행할 것")
        return 1
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        print("[web] npx 를 찾지 못함 — Node.js 가 필요하다")
        return 1
    return subprocess.call([npx, "vite", "build"], cwd=APP)


def run(argv, title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    return subprocess.call([sys.executable, "-m", *argv], cwd=ROOT)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="제출물 재빌드")
    ap.add_argument("--rehearse", action="store_true")
    ap.add_argument("--check", action="store_true", help="게이트만 실행")
    ap.add_argument("--split", action="store_true",
                    help="코드와 DB 를 나누어 낸다 (제출물 3종). 기본은 합본")
    a = ap.parse_args()

    # 화면을 먼저 빌드한다. 게이트와 패키징이 같은 `dist` 를 보게 하려면
    # 순서가 이래야 한다 — 게이트가 낡은 화면을 통과시키고 그 다음에 새 화면이
    # 실리면, 검사한 것과 낸 것이 다른 물건이 된다.
    if not a.check:
        print(f"\n{'=' * 60}\n1. 화면 빌드\n{'=' * 60}")
        if build_web():
            return 1
    if run(["tools.audit"], "2. 게이트"):
        print("\n게이트 실패 — 빌드하지 않았다")
        return 1
    if a.check:
        return 0
    argv = ["tools.package"]
    if a.split:
        argv.append("--split")
    if a.rehearse:
        argv.append("--rehearse")
    if run(argv, "3. 패키징" + (" + 리허설" if a.rehearse else "")):
        return 1
    name = "KB_Previl_service.zip" if a.split else "KB_Previl_all.zip"
    check = ["tools.audit", "--zip", str(ROOT / "SUBMISSION" / name)]
    if not a.split:
        check.append("--allow-db")
    return run(check, "4. zip 내용 검사")


if __name__ == "__main__":
    sys.exit(main())
