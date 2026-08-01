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

from .manifest import (ALLOWED_SUFFIXES, BANNED_COMMENT, DB_NAME, DB_TABLES,
                       ENTRY_CLI, ENTRY_IMPORT, FORBIDDEN_DIRS,
                       FORBIDDEN_NAMES, HEADERS, MAX_LINES, ROOT, SHIP_FILES,
                       SHIP_PKGS, SHIP_TREES, SIZE_EXEMPT, TREE_EXCLUDE,
                       TREE_EXCLUDE_DIRS, TREE_EXCLUDE_FILES, ZIP_ROOT)
from .strip import StripError, strip_python, strip_web_batch


def _modules():
    """Dotted name -> path, walking subpackages. `x/y/__init__.py` is `x.y`."""
    out = {}
    for pkg in SHIP_PKGS:
        for p in sorted((ROOT / pkg).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            parts = p.relative_to(ROOT).with_suffix("").parts
            name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            out[name] = p
    return out


def _package_of(path):
    return ".".join(path.relative_to(ROOT).parent.parts)


def _imports(path, known):
    tree = ast.parse(path.read_text("utf-8"))
    here = _package_of(path)
    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            found |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            parts = here.split(".")
            base = ".".join(parts[:len(parts) - n.level + 1]) if n.level else ""
            if n.level and n.module:
                found.add(f"{base}.{n.module}" if base else n.module)
            elif n.level:
                found |= {f"{base}.{a.name}" if base else a.name
                          for a in n.names}
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
        stack.extend(_imports(mods[m], known) - seen)
    return mods, seen


# `importlib.import_module(name)` 류. 이름이 리터럴이 아니면 정적으로 못 푼다.
DYNAMIC_CALLS = {"import_module", "run_module", "run_path", "__import__"}


def _dynamic_refs(path, known):
    """문자열로 지목하는 모듈과, 정적으로 풀 수 없는 동적 호출의 줄 번호.

    `bootstrap` 이 `python -m pipeline.sgis` 를 부르는 것을 import 걷기는 보지
    못한다. 실제로 그래서 출하 목록이 모자랐고, ENTRY_CLI 를 손으로 채워 막았다.
    손 목록은 다음에 또 어긋나므로 문자열 자체를 근거로 삼는다.
    """
    tree = ast.parse(path.read_text("utf-8"))
    named, unresolved = set(), []
    for n in ast.walk(tree):
        # 점이 있는 것만 — 최상위 패키지 이름(`"model"`)은 폴더명·라벨로도 쓰이고,
        # `__init__.py` 는 어차피 전부 실린다.
        if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and "." in n.value and n.value in known):
            named.add(n.value)
        elif isinstance(n, ast.Call):
            fn = n.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            arg = n.args[0] if n.args else None
            if name in DYNAMIC_CALLS and not (
                    isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                unresolved.append(n.lineno)
    return named, unresolved


STRIPPED = {".py", ".ts", ".tsx", ".css"}


def ship_items():
    """(원본 경로, zip 안 경로) 전부 — 게이트와 패키징의 유일한 출처.

    둘이 각자 계산하면 한쪽만 보는 파일이 생긴다. 실제로 `vite.config.ts` 와
    `tokens.css` 가 그렇게 빠져 있었다.
    """
    mods, reach = closure()
    files = [mods[m] for m in sorted(reach)]
    for pkg in SHIP_PKGS:
        files += [p for p in sorted((ROOT / pkg).rglob("__init__.py"))
                  if "__pycache__" not in p.parts]
    items = [(p, p.relative_to(ROOT).as_posix())
             for p in dict.fromkeys(files)]
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
    seen, out = set(), []
    for src, arc in items:
        if arc not in seen:
            seen.add(arc)
            out.append((src, f"{ZIP_ROOT}/{arc}"))
    return out


def is_stripped(src, arc):
    """빌드된 번들(`web/`)은 그대로 넣는다 — 소스가 아니다."""
    return src.suffix in STRIPPED and not arc.startswith(f"{ZIP_ROOT}/web/")


def ship_paths():
    """게이트가 보는 파일 = 실제로 벗겨져 zip 에 들어가는 파일."""
    items = [(s, a) for s, a in ship_items() if is_stripped(s, a)]
    py = [s for s, _ in items if s.suffix == ".py"]
    web = [s for s, _ in items if s.suffix != ".py"]
    return py, web


def gate_closure(v):
    mods, reach = closure()
    dead = sorted(set(mods) - reach)
    print(f"[closure] 진입점 도달 {len(reach)} / 전체 {len(mods)} 모듈")
    if v:
        for m in dead:
            print(f"    출하 제외  {m}")
    print(f"[closure] 출하 제외 {len(dead)}개 — 데드코드 아님(저장소 보관)")
    bad = [(m, "진입점 없음") for m in (*ENTRY_IMPORT, *ENTRY_CLI) if m not in mods]
    known = set(mods)
    for m in sorted(reach):
        named, unresolved = _dynamic_refs(mods[m], known)
        bad += [(m, f"{ln}행 동적 import 를 정적으로 풀 수 없다") for ln in unresolved]
        bad += [(m, f"«{ref}» 를 문자열로 부르는데 출하 목록 밖이다")
                for ref in sorted(named - reach)]
    for m, why in bad:
        print(f"    FAIL {m} — {why}")
    return len(bad)


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


_WEB_CACHE = {}


def shipped_text(path):
    """zip 에 실제로 들어가는 내용 — 주석과 독스트링을 걷어낸 것."""
    path = Path(path)
    rel = path.relative_to(ROOT).as_posix()
    if path.suffix == ".py":
        # errors="strict": 깨진 바이트를 조용히 버리면 다른 유효 코드가 된다.
        return strip_python(path.read_text("utf-8"), HEADERS.get(rel), rel)
    if path.resolve() not in _WEB_CACHE:
        _, web = ship_paths()
        _WEB_CACHE.update(strip_web_batch(web))
    return _WEB_CACHE[path.resolve()]


def _residual_docstrings(text):
    tree = ast.parse(text)
    found = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)) and ast.get_docstring(n):
            found.append(("module" if isinstance(n, ast.Module) else "def",
                          getattr(n, "lineno", 1)))
    return found


def _web_residue(web, stripped):
    """벗겨낸 결과를 한 번 더 벗겨 본다.

    주석이 하나라도 남았으면 두 번째 통과가 그것을 지워 결과가 달라진다.
    «줄이 // 로 시작하는가» 같은 모양 검사는 인라인 주석과 JSX `{/* */}` 를
    통째로 놓쳤다 — 실제로 17파일 132줄이 그렇게 새어 나갔다.
    """
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="kb-residue-"))
    try:
        mirror = {}
        for i, path in enumerate(web):
            copy = tmp / f"{i}{path.suffix}"
            copy.write_text(stripped[path], encoding="utf-8")
            mirror[copy.resolve()] = path
        again = strip_web_batch(list(mirror))
        return [mirror[c] for c, text in again.items()
                if text != stripped[mirror[c]]]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def gate_comments(v):
    """벗겨낸 결과에 주석·독스트링·서사 문구가 남지 않았는지."""
    py, web = ship_paths()
    bad, before, after = [], 0, 0
    stripped = {}
    for path in py + web:
        rel = path.relative_to(ROOT).as_posix()
        before += path.read_text("utf-8").count("\n") + 1
        try:
            out = shipped_text(path)
        except (SyntaxError, StripError, UnicodeDecodeError) as exc:
            bad.append((rel, f"제거 실패 — {exc}"))
            continue
        stripped[path] = out
        after += out.count("\n") + 1
        if path.suffix != ".py":
            continue
        for ln, txt in _comment_spans(out):
            bad.append((rel, f"{ln}행 주석 남음 {txt[:40]}"))
        docs = _residual_docstrings(out)
        extra = [d for d in docs if d[0] != "module"]
        if extra:
            bad.append((rel, f"독스트링 {len(extra)}개 남음"))
        if len([d for d in docs if d[0] == "module"]) != (1 if HEADERS.get(rel) else 0):
            bad.append((rel, "모듈 한 줄 설명 누락"))

    for path in py + web:
        rel = path.relative_to(ROOT).as_posix()
        header = HEADERS.get(rel) or ""
        for token in BANNED_COMMENT:
            if token in header:
                bad.append((rel, f"모듈 설명에 서사 «{token}»"))
        if not header.isascii():
            bad.append((rel, "모듈 설명이 ASCII 가 아님 — 주석은 영어만"))

    residue = _web_residue([p for p in web if p in stripped], stripped)
    for path in residue:
        bad.append((path.relative_to(ROOT).as_posix(),
                    "재제거하면 또 달라진다 — 주석이 남아 있다"))

    saved = before - after
    print(f"[comments] 위반 {len(bad)}건 · "
          f"{before:,}줄 → {after:,}줄 ({saved:,}줄 제거, {saved / before * 100:.0f}%)")
    for rel, why in bad[:None if v else 20]:
        print(f"    {rel}  {why}")
    return len(bad)


def gate_size(v):
    """출하되는 파일 기준 — 벗겨낸 뒤 줄 수. 면제는 사유와 함께 통과시킨다."""
    py, web = ship_paths()
    over, allowed = [], []
    for path in py + [p for p in web if p.suffix != ".css"]:
        rel = path.relative_to(ROOT).as_posix()
        try:
            n = shipped_text(path).count("\n") + 1
        except SyntaxError:
            n = path.read_text("utf-8").count("\n") + 1
        if n <= MAX_LINES:
            continue
        (allowed if rel in SIZE_EXEMPT else over).append((n, rel))
    over.sort(reverse=True)
    allowed.sort(reverse=True)
    print(f"[size] {MAX_LINES}줄 초과 {len(over) + len(allowed)}개 "
          f"— 면제 {len(allowed)} · 위반 {len(over)}")
    for n, rel in over:
        print(f"    위반  {n:>5}줄  {rel}")
    if v:
        for n, rel in allowed:
            print(f"    면제  {n:>5}줄  {rel} — {SIZE_EXEMPT[rel]}")
    stale = sorted(set(SIZE_EXEMPT) - {r for _, r in allowed})
    for rel in stale:
        print(f"    면제 불필요  {rel} — 이미 {MAX_LINES}줄 이하다")
    return len(over) + len(stale)


REQUIRED_IN_ZIP = ("README.md", "run.py", "requirements.txt",
                   "requirements-full.txt", "verify.ipynb",
                   "service/app.py", "web/index.html")


def _sqlite_verdict(blob):
    """진짜 SQLite 이고, 열리고, 서빙 표가 차 있는지. 아니면 이유를 돌려준다."""
    import shutil
    import sqlite3
    import tempfile
    if not blob.startswith(b"SQLite format 3\x00"):
        return "SQLite 파일이 아니다"
    tmp = Path(tempfile.mkdtemp(prefix="kb-db-"))
    try:
        p = tmp / DB_NAME
        p.write_bytes(blob)
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            verdict = con.execute("PRAGMA quick_check").fetchone()[0]
            if verdict != "ok":
                return f"quick_check — {verdict}"
            for table in DB_TABLES:
                n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                if not n:
                    return f"{table} 이 비어 있다"
        finally:
            con.close()
    except sqlite3.Error as exc:
        return f"열 수 없다 — {exc}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return None


def gate_zip(v, zip_path, allow_db=False):
    """zip 이 계약대로인지. 없는 zip 은 «검사할 것이 없음» 이 아니라 실패다.

    이름만 맞추면 내용이 빈 껍데기도 통과한다 — 필수 7개와 DB 이름만 담은
    8항목짜리 가짜 zip 이 실제로 통과했다. 그래서 출하 목록과 정확히 대조하고
    바이트까지 맞춰 본다.
    """
    import zipfile
    if not Path(zip_path).is_file():
        print(f"[zip] FAIL — {zip_path} 없음. 먼저 빌드할 것")
        return 1
    archive = zipfile.ZipFile(zip_path)
    names = archive.namelist()
    bad = []
    if archive.testzip() is not None:
        bad.append((archive.testzip(), "CRC 오류"))
    if len(names) != len(set(names)):
        seen = set()
        bad += [(n, "중복 항목") for n in names if n in seen or seen.add(n)]
    roots = {n.split("/")[0] for n in names}
    if roots != {ZIP_ROOT}:
        bad.append((", ".join(sorted(roots)), f"최상위가 {ZIP_ROOT} 하나가 아니다"))
    for must in REQUIRED_IN_ZIP:
        if f"{ZIP_ROOT}/{must}" not in names:
            bad.append((must, "필수 항목 누락"))

    db_arc = f"{ZIP_ROOT}/{DB_NAME}"
    db_entries = [n for n in names if n.endswith(".db")]
    if allow_db and db_entries != [db_arc]:
        bad.append((", ".join(db_entries) or "(없음)",
                    f"합본에는 {db_arc} 하나만 있어야 한다"))
    elif allow_db:
        why = _sqlite_verdict(archive.read(db_arc))
        if why:
            bad.append((db_arc, f"DB 가 쓸 수 없다 — {why}"))

    expected = {arc: (src, is_stripped(src, arc)) for src, arc in ship_items()}
    want = set(expected) | ({db_arc} if allow_db else set())
    have = set(names)
    bad += [(n, "출하 목록에 있는데 zip 에 없다") for n in sorted(want - have)]
    bad += [(n, "출하 목록에 없는데 zip 에 있다") for n in sorted(have - want)]
    stale = 0
    for arc in sorted((want & have) - {db_arc}):
        src, stripped = expected[arc]
        try:
            wanted = shipped_text(src).encode("utf-8") if stripped else src.read_bytes()
        except (SyntaxError, StripError, UnicodeDecodeError) as exc:
            bad.append((arc, f"지금 다시 만들 수 없다 — {exc}"))
            continue
        if archive.read(arc) != wanted:
            stale += 1
            bad.append((arc, "내용이 지금 만들 것과 다르다 — 낡은 zip"))

    forbidden = set(FORBIDDEN_NAMES)
    allowed_suffixes = set(ALLOWED_SUFFIXES)
    if allow_db:
        forbidden.discard("kb-demo.db")
        allowed_suffixes.add(".db")
    for n in names:
        parts = n.split("/")
        name = parts[-1]
        if ".." in parts or n.startswith("/") or ":" in parts[0]:
            bad.append((n, "경로 탈출"))
            continue
        if n == f"{ZIP_ROOT}/README.md":
            continue                      # 유일하게 허용되는 문서
        if name in forbidden or FORBIDDEN_DIRS & set(parts[:-1]):
            bad.append((n, "금지 이름·폴더"))
        elif name.endswith(".md") and n != f"{ZIP_ROOT}/README.md":
            bad.append((n, "문서 — 루트 README 하나만 허용"))
        elif TREE_EXCLUDE_DIRS & set(parts[:-1]) or name in TREE_EXCLUDE_FILES:
            bad.append((n, "캐시·빌드 산출물"))
        elif Path(name).suffix.lower() not in allowed_suffixes:
            # 블록리스트는 빠뜨린 패턴을 못 잡는다. 모르는 확장자는 일단 세운다.
            bad.append((n, f"허용 목록에 없는 확장자 {Path(name).suffix or '(없음)'}"))
    print(f"[zip] {len(names):,}개 항목 · 위반 {len(bad)}건"
          + (f" (내용 불일치 {stale}건)" if stale else ""))
    for n, why in bad[:None if v else 20]:
        print(f"    {n}  — {why}")
    if len(bad) > 20 and not v:
        print(f"    … 외 {len(bad) - 20}건 (-v 로 전부)")
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
            print("[behaviour] FAIL — kb-demo.db 없어 검사를 돌릴 수 없다. "
                  "«검사 못 함» 을 통과로 세지 않는다")
            return 1
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


def stage_frontend(outer):
    """zip 에 들어가는 바로 그 프론트 항목을 그대로 편다.

    설정과 토큰 CSS 를 원본에서 복사하면 게이트가 빌드한 트리와 zip 의 바이트가
    달라져, 그 두 파일의 변경만 검사를 빠져나간다.
    """
    import shutil
    prefix = f"{ZIP_ROOT}/frontend/"
    count = 0
    for src, arc in ship_items():
        if not arc.startswith(prefix):
            continue
        dst = outer / arc[len(prefix):]
        dst.parent.mkdir(parents=True, exist_ok=True)
        if is_stripped(src, arc):
            dst.write_text(shipped_text(src), encoding="utf-8")
        else:
            shutil.copy2(src, dst)
        count += 1
    return count


def gate_frontend(v):
    """벗겨낸 프론트 소스가 그대로 타입 검사와 빌드를 통과하는지.

    파이썬은 제거 후 `ast.parse` 로 확인되지만 TS·CSS 에는 그 확인이 없다.
    `tsc` 가 타입을, `vite build` 가 CSS 까지 파싱한다. 서빙되는 `web/` 은
    원본에서 빌드되므로, 이것이 깨져도 화면은 멀쩡하고 소스만 조용히 망가진다.
    """
    import shutil
    import subprocess
    import tempfile
    app = ROOT / "frontend" / "app"
    if not (app / "node_modules").is_dir():
        print("[frontend] FAIL — node_modules 없음. `npm install` 후 다시 돌릴 것")
        return 1
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        print("[frontend] FAIL — npx 없음. Node.js 가 필요하다")
        return 1

    # 저장소 레이아웃을 그대로 재현한다 — main.tsx 가 app 바깥의 토큰 CSS 를
    # 부르므로 app 만 떼어 놓으면 여기서만 깨지고 zip 에서는 안 깨진다.
    outer = Path(tempfile.mkdtemp(prefix="kb-ts-"))
    tmp = outer / "app"
    tmp.mkdir()
    link = tmp / "node_modules"
    try:
        staged = stage_frontend(outer)
        if not (tmp / "index.html").is_file():
            print(f"[frontend] FAIL — 출하 목록에 프론트 소스가 없다 ({staged}개)")
            return 1
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link),
                            str(app / "node_modules")], capture_output=True)
        else:
            link.symlink_to(app / "node_modules")
        if not link.exists():
            print("[frontend] FAIL — node_modules 연결 실패")
            return 1
        steps = (("tsc --noEmit", [npx, "tsc", "--noEmit", "-p", "tsconfig.json"]),
                 ("vite build", [npx, "vite", "build", "--logLevel", "warn",
                                 "--outDir", str(tmp / "_out")]))
        failed = 0
        for label, cmd in steps:
            proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=900)
            print(f"[frontend] 벗겨낸 소스 {label} — exit {proc.returncode}")
            if proc.returncode:
                failed += 1
                out = ((proc.stdout or "") + (proc.stderr or "")).splitlines()
                for ln in [x for x in out if x.strip()][:20]:
                    print(f"    {ln}")
        return failed
    finally:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)
        elif link.is_symlink():
            link.unlink()
        shutil.rmtree(outer, ignore_errors=True)


GATES = {"closure": gate_closure, "comments": gate_comments, "size": gate_size,
         "behaviour": gate_behaviour, "frontend": gate_frontend}


def main():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="제출물 게이트")
    for name in GATES:
        ap.add_argument(f"--{name}", action="store_true")
    ap.add_argument("--zip", metavar="PATH", help="빌드된 코드 zip 검사")
    ap.add_argument("--allow-db", action="store_true",
                    help="--zip 과 함께 — 코드와 DB 를 한 zip 에 담은 합본")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    picked = [n for n in GATES if getattr(a, n)]
    if not picked and not a.zip:
        picked = list(GATES)
    fails = sum(GATES[n](a.verbose) for n in picked)
    if a.zip:
        fails += gate_zip(a.verbose, a.zip, a.allow_db)
    print("\n" + ("게이트 통과" if not fails else f"게이트 실패 — 위반 {fails}건"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
