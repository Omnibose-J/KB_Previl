"""출하 소스에서 주석과 독스트링을 걷어낸다. 코드는 한 글자도 바꾸지 않는다."""
import ast
import io
import re
import tokenize


def _docstring_spans(tree):
    """독스트링 노드의 (시작줄, 끝줄, 그 몸통이 독스트링뿐인가)."""
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        alone = len(body) == 1 and not isinstance(node, ast.Module)
        spans.append((first.lineno, first.end_lineno, alone,
                      first.col_offset))
    return spans


def strip_python(src, header=None):
    """주석·독스트링 제거. header 를 주면 한 줄 모듈 독스트링으로 넣는다."""
    tree = ast.parse(src)
    lines = src.splitlines()
    drop = set()
    replace = {}
    for start, end, alone, col in _docstring_spans(tree):
        for ln in range(start, end + 1):
            drop.add(ln)
        if alone:
            replace[start] = " " * col + "pass"

    cut = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                cut.setdefault(tok.start[0], tok.start[1])
    except (tokenize.TokenError, IndentationError):
        pass

    out = []
    for i, line in enumerate(lines, 1):
        if i in replace:
            out.append(replace[i])
            continue
        if i in drop:
            continue
        if i in cut:
            trimmed = line[:cut[i]].rstrip()
            if not trimmed:
                continue
            out.append(trimmed)
            continue
        out.append(line.rstrip())

    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n\n", text).strip("\n")
    if header:
        anchor = 0
        body = text.split("\n")
        while anchor < len(body) and body[anchor].startswith("from __future__"):
            anchor += 1
        body.insert(anchor, f'"""{header}"""')
        if anchor + 1 < len(body) and body[anchor + 1].strip():
            body.insert(anchor + 1, "")
        text = "\n".join(body)
    ast.parse(text)
    return text + "\n"


_TS_LINE = re.compile(r"^\s*(//|/\*|\*/?)")


def strip_ts(src):
    """줄 전체가 주석인 것만 지운다. 문자열 안의 // 를 건드리지 않기 위해서다."""
    out, in_block = [], False
    for line in src.splitlines():
        s = line.strip()
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("/*"):
            if "*/" not in s:
                in_block = True
            continue
        if _TS_LINE.match(line) and not s.startswith("*/"):
            continue
        out.append(line.rstrip())
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n\n", text).strip("\n") + "\n"
