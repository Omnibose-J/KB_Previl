"""출하 소스에서 주석과 독스트링을 걷어낸다. 코드는 한 글자도 바꾸지 않는다.

애매한 입력은 추측하지 않고 실패시킨다 — 조용히 바뀐 코드는 게이트도 못 잡는다.
"""
import ast
import io
import json
import re
import shutil
import subprocess
import tokenize
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "strip_web.mjs"


class StripError(RuntimeError):
    """제거가 코드 의미를 바꿀 수 있어 중단했다."""


def _docstring_spans(tree):
    """(노드, 독스트링 Expr) — 독스트링이 있는 노드만."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.append((node, first))
    return out


def _guard_same_line(lines, expr, where):
    """독스트링이 코드와 같은 물리 줄에 있으면 중단한다.

    줄 단위로 지우면 `\"\"\"doc\"\"\"; x = 1` 의 `x = 1` 이 함께 사라지는데,
    남은 코드는 여전히 문법이 맞아서 파싱 검사를 통과한다.
    """
    before = lines[expr.lineno - 1][:expr.col_offset]
    after = lines[expr.end_lineno - 1][expr.end_col_offset:]
    if before.strip():
        raise StripError(f"{where}:{expr.lineno} 독스트링 앞에 코드가 있다")
    if after.strip():
        raise StripError(f"{where}:{expr.end_lineno} 독스트링 뒤에 코드가 있다 "
                         f"— 줄을 나눈 뒤 다시 빌드할 것")


def strip_python(src, header=None, where="<source>"):
    """주석·독스트링 제거. header 를 주면 한 줄 모듈 독스트링으로 넣는다."""
    tree = ast.parse(src)
    lines = src.splitlines()
    drop, replace = set(), {}
    for node, expr in _docstring_spans(tree):
        _guard_same_line(lines, expr, where)
        drop.update(range(expr.lineno, expr.end_lineno + 1))
        if len(node.body) == 1 and not isinstance(node, ast.Module):
            replace[expr.lineno] = " " * expr.col_offset + "pass"

    cut = {}
    shebang = bool(lines) and lines[0].startswith("#!")
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.COMMENT:
                continue
            if shebang and tok.start[0] == 1:
                continue          # 셔뱅은 주석 모양이지만 실행에 필요하다
            cut.setdefault(tok.start[0], tok.start[1])
    except (tokenize.TokenError, IndentationError):
        pass

    out = []
    for i, line in enumerate(lines, 1):
        if i in replace:
            out.append(replace[i])
        elif i in drop:
            continue
        elif i in cut:
            trimmed = line[:cut[i]].rstrip()
            if trimmed:
                out.append(trimmed)
        else:
            out.append(line.rstrip())

    text = re.sub(r"\n{3,}", "\n\n\n", "\n".join(out)).strip("\n")
    if header:
        body = text.split("\n")
        at = 1 if shebang else 0
        # 모듈 독스트링은 `from __future__` 보다 앞이어야 한다. 뒤에 넣으면
        # 그냥 문자열 하나가 되고, 괄호형 future import 안이면 구문이 깨진다.
        body.insert(at, f'"""{header}"""')
        if at + 1 < len(body) and body[at + 1].strip():
            body.insert(at + 1, "")
        text = "\n".join(body)
    ast.parse(text)
    return text + "\n"


def _node():
    exe = shutil.which("node") or shutil.which("node.exe")
    if not exe:
        raise StripError("node 를 찾지 못했다 — TS·CSS 주석 제거에 필요하다")
    if not SCRIPT.is_file():
        raise StripError(f"{SCRIPT.name} 없음")
    return exe


def strip_web_batch(paths):
    """TS·TSX·CSS 를 한 번에 벗긴다. 실제 파서를 쓰므로 node 가 필요하다."""
    paths = [Path(p).resolve() for p in paths]
    if not paths:
        return {}
    payload = json.dumps({"files": [str(p) for p in paths]})
    proc = subprocess.run([_node(), str(SCRIPT)], input=payload,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="strict", timeout=600)
    if proc.returncode != 0:
        raise StripError(f"strip_web.mjs 실패 (exit {proc.returncode})\n"
                         f"{(proc.stderr or proc.stdout)[-2000:]}")
    result = json.loads(proc.stdout)
    if result["fail"]:
        first = sorted(result["fail"].items())[0]
        raise StripError(f"{Path(first[0]).name}: {first[1]}")
    return {Path(k): v for k, v in result["ok"].items()}
