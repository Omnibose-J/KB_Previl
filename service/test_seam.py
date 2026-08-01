"""분해 이음매 구조 검사 — DB 접근이 갈아끼울 수 있는 한 곳으로만 흐르는지.

`service/api.py` 를 패키지로 나눌 때 33개 시험이 한 번에 무너졌다. 원인은
동작이 아니라 결합 방식이었다: 소비자가 `from .base import readonly_connection`
으로 이름을 가져오면 그 시점의 함수가 박혀, 시험이 `api.base.readonly_connection`
을 갈아끼워도 닿지 않는다. 지금은 전부 속성 접근으로 부르지만 그것을 지키는
장치가 없어 다음 편집에서 조용히 되돌아갈 수 있다. 이 파일이 그 장치다.
"""
import ast
from pathlib import Path

SERVICE = Path(__file__).resolve().parent
API = SERVICE / "api"
SEAM = API / "base.py"
# demo_db 는 요청 경로가 아니라 CLI 기본값으로 한 번 읽는다. 시험이 갈아끼우는
# 대상이 아니므로 이음매가 아니다.
DB_PATH_ALLOWED = {SEAM, SERVICE / "demo_db.py"}


def _sources():
    for path in sorted(SERVICE.rglob("*.py")):
        if path.name.startswith("test_") or "__pycache__" in path.parts:
            continue
        yield path


def _imported(path):
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                yield node.lineno, alias.name


def test_readonly_connection_is_never_name_imported():
    offenders = [f"{p.relative_to(SERVICE).as_posix()}:{ln}"
                 for p in _sources()
                 for ln, name in _imported(p)
                 if name == "readonly_connection"]
    assert not offenders, (
        "`base.readonly_connection()` 으로 부를 것 — 이름으로 가져오면 "
        f"monkeypatch 이음매가 끊긴다: {offenders}")


def test_db_path_is_read_only_in_the_seam():
    offenders = [f"{p.relative_to(SERVICE).as_posix()}:{ln}"
                 for p in _sources() if p not in DB_PATH_ALLOWED
                 for ln, name in _imported(p)
                 if name == "DB_PATH"]
    assert not offenders, (
        "DB_PATH 사본이 생기면 시험이 갈아끼운 경로와 서빙이 여는 경로가 "
        f"갈라진다. api/base.py 를 통할 것: {offenders}")


def test_package_exports_do_not_reopen_the_seam():
    names = set()
    for node in ast.walk(ast.parse((API / "__init__.py").read_text("utf-8"))):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.asname or alias.name for alias in node.names}
    assert "readonly_connection" not in names, (
        "api 패키지가 readonly_connection 을 다시 내보내면 갈아끼울 자리가 "
        "둘이 된다 — 하나만 남길 것")
