"""Submission gates. Every completion condition in the criteria file runs from here.

    python -m tools.audit            # all gates
    python -m tools.audit --comments # one gate
"""
import argparse
import ast
import io
import os
import sys
import tokenize
from pathlib import Path

from .manifest import (BANNED_COMMENT, ENTRY_CLI, ENTRY_IMPORT, FORBIDDEN_DIRS,
                       FORBIDDEN_NAMES, HEADERS, MAX_LINES, ROOT, SHIP_PKGS)
from .strip import strip_python, strip_ts


def _modules():
    out = {}
    for pkg in SHIP_PKGS:
        for p in sorted((ROOT / pkg).glob("*.py")):
            out[f"{pkg}.{p.stem}"] = p
    return out


def _imports(path, pkg, known):
    tree = ast.parse(path.read_text("utf-8", errors="ignore"))
    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            found |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            if n.level and n.module:
                found.add(f"{pkg}.{n.module}")
            elif n.level:
                found |= {f"{pkg}.{a.name}" for a in n.names}
            elif n.module:
                found.add(n.module)
                found |= {f"{n.module}.{a.name}" for a in n.names}
    return found & known


def closure():
    """Modules reachable from the entry points, following imports and CLI calls."""
    mods = _modules()
    known = set(mods)
    seen, stack = set(), [m for m in (*ENTRY_IMPORT, *ENTRY_CLI) if m in known]
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack.extend(_imports(mods[m], m.split(".")[0], known) - seen)
    return mods, seen


def ship_paths():
    """Every source file that goes into the code zip."""
    mods, reach = closure()
    files = [mods[m] for m in sorted(reach)]
    files += [ROOT / p / "__init__.py" for p in SHIP_PKGS
              if (ROOT / p / "__init__.py").is_file()]
    for extra in ("run.py",):
        if (ROOT / extra).is_file():
            files.append(ROOT / extra)
    ts = sorted((ROOT / "frontend/app/src").rglob("*.ts")) + \
        sorted((ROOT / "frontend/app/src").rglob("*.tsx"))
    return files, ts


def gate_closure(v):
    mods, reach = closure()
    dead = sorted(set(mods) - reach)
    print(f"[closure] 진입점 도달 {len(reach)} / 전체 {len(mods)} 모듈")
    if v:
        for m in dead:
            print(f"    출하 제외  {m}")
    print(f"[closure] 출하 제외 {len(dead)}개 — 데드코드 아님(저장소 보관)")
    missing = [m for m in (*ENTRY_IMPORT, *ENTRY_CLI) if m not in mods]
    for m in missing:
        print(f"    FAIL 진입점 없음: {m}")
    return len(missing)


def _comment_spans(src):
    """(lineno, text) for every comment token."""
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return out


def shipped_text(path):
    """zip 에 실제로 들어가는 내용 — 주석과 독스트링을 걷어낸 것."""
    rel = path.relative_to(ROOT).as_posix()
    src = path.read_text("utf-8", errors="ignore")
    if path.suffix == ".py":
        return strip_python(src, HEADERS.get(rel))
    return strip_ts(src)


def _residual_docstrings(text):
    tree = ast.parse(text)
    found = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)) and ast.get_docstring(n):
            found.append(("module" if isinstance(n, ast.Module) else "def",
                          getattr(n, "lineno", 1)))
    return found


def gate_comments(v):
    """벗겨낸 결과에 주석·독스트링·서사 문구가 남지 않았는지."""
    py, ts = ship_paths()
    bad, before, after = [], 0, 0
    for path in py + ts:
        rel = path.relative_to(ROOT).as_posix()
        src = path.read_text("utf-8", errors="ignore")
        before += src.count("\n") + 1
        try:
            out = shipped_text(path)
        except SyntaxError as exc:
            bad.append((rel, f"제거 후 파싱 실패 — {exc}"))
            continue
        after += out.count("\n") + 1
        if path.suffix == ".py":
            for ln, txt in _comment_spans(out):
                bad.append((rel, f"{ln}행 주석 남음 {txt[:40]}"))
            docs = _residual_docstrings(out)
            expected = 1 if HEADERS.get(rel) else 0
            extra = [d for d in docs if d[0] != "module"]
            if extra:
                bad.append((rel, f"독스트링 {len(extra)}개 남음"))
            if len([d for d in docs if d[0] == "module"]) != expected:
                bad.append((rel, "모듈 한 줄 설명 누락"))
        else:
            for i, line in enumerate(out.splitlines(), 1):
                s = line.strip()
                if s.startswith("//") or s.startswith("/*"):
                    bad.append((rel, f"{i}행 주석 남음 {s[:40]}"))
        header = HEADERS.get(rel) or ""
        for token in BANNED_COMMENT:
            if token in header:
                bad.append((rel, f"모듈 설명에 서사 «{token}»"))
        if not header.isascii():
            bad.append((rel, "모듈 설명이 ASCII 가 아님 — 주석은 영어만"))

    saved = before - after
    print(f"[comments] 위반 {len(bad)}건 · "
          f"{before:,}줄 → {after:,}줄 ({saved:,}줄 제거, {saved/before*100:.0f}%)")
    for rel, why in bad[:None if v else 20]:
        print(f"    {rel}  {why}")
    return len(bad)


def gate_size(v):
    """출하되는 파일 기준 — 벗겨낸 뒤 줄 수."""
    py, ts = ship_paths()
    over = []
    for path in py + ts:
        try:
            n = shipped_text(path).count("\n") + 1
        except SyntaxError:
            n = path.read_text("utf-8", errors="ignore").count("\n") + 1
        if n > MAX_LINES:
            over.append((n, path.relative_to(ROOT).as_posix()))
    over.sort(reverse=True)
    print(f"[size] {MAX_LINES}줄 초과 {len(over)}개")
    for n, rel in over:
        print(f"    {n:>5}줄  {rel}")
    return len(over)


def gate_zip(v, zip_path):
    import zipfile
    if not Path(zip_path).is_file():
        print(f"[zip] {zip_path} 없음 — 건너뜀")
        return 0
    names = zipfile.ZipFile(zip_path).namelist()
    bad = []
    for n in names:
        parts = n.split("/")
        if parts[-1] in FORBIDDEN_NAMES or FORBIDDEN_DIRS & set(parts[:-1]):
            bad.append(n)
        if parts[-1].endswith(".md") and parts[-1] != "README.md":
            bad.append(n)
    print(f"[zip] {len(names):,}개 항목 · 금지 {len(bad)}건")
    for n in bad[:20]:
        print(f"    {n}")
    return len(bad)


def gate_behaviour(v):
    """벗겨낸 소스로 기존 서빙 계약 시험을 그대로 돌린다."""
    import shutil
    import subprocess
    import tempfile
    py, _ = ship_paths()
    tmp = Path(tempfile.mkdtemp(prefix="kb-strip-"))
    try:
        for path in py:
            rel = path.relative_to(ROOT)
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(shipped_text(path), encoding="utf-8")
        for pkg in SHIP_PKGS:
            init = tmp / pkg / "__init__.py"
            init.parent.mkdir(parents=True, exist_ok=True)
            init.touch(exist_ok=True)
        tests = [p for p in (ROOT / "service").glob("test_*.py")]
        for t in tests:
            shutil.copy2(t, tmp / "service" / t.name)
        db = ROOT / "kb-demo.db"
        if not db.is_file():
            print("[behaviour] kb-demo.db 없음 — 건너뜀")
            return 0
        env = dict(os.environ, KB_DB=str(db), PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "service", "-q", "--no-header",
             "-p", "no:cacheprovider"],
            cwd=tmp, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800)
        tail = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        print(f"[behaviour] 벗겨낸 트리에서 pytest — exit {proc.returncode}")
        for ln in tail[-3:]:
            print(f"    {ln}")
        if proc.returncode and v:
            print((proc.stdout or proc.stderr)[-4000:])
        return 1 if proc.returncode else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


GATES = {"closure": gate_closure, "comments": gate_comments, "size": gate_size,
         "behaviour": gate_behaviour}


def main():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="제출물 게이트")
    for name in GATES:
        ap.add_argument(f"--{name}", action="store_true")
    ap.add_argument("--zip", metavar="PATH", help="빌드된 코드 zip 검사")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    picked = [n for n in GATES if getattr(a, n)]
    if not picked and not a.zip:
        picked = list(GATES)
    fails = sum(GATES[n](a.verbose) for n in picked)
    if a.zip:
        fails += gate_zip(a.verbose, a.zip)
    print("\n" + ("게이트 통과" if not fails else f"게이트 실패 — 위반 {fails}건"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
