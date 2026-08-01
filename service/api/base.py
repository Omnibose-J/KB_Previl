import sqlite3
from contextlib import contextmanager

from pipeline.config import DB_PATH


class ApiInputError(ValueError):
    """The caller supplied a value outside the public API contract."""


class ResourceNotFoundError(LookupError):
    """A syntactically valid public resource does not exist."""


class DatabaseUnavailableError(RuntimeError):
    """The read-only SQLite dependency could not serve a query."""


class ViewportTooLargeError(ApiInputError):
    """The requested viewport contains more cells than the API cap."""

    def __init__(self, max_cells):
        super().__init__(
            f"격자 수가 상한 {max_cells}개를 넘습니다. 지도를 확대해 주세요."
        )
        self.max_cells = max_cells


MAX_GRID_CELLS = 2_000


@contextmanager
def readonly_connection():
    """Open the shared database in SQLite's enforced read-only mode."""

    uri = f"{DB_PATH.resolve().as_uri()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError(
            f"읽기 전용 DB를 열 수 없습니다: {DB_PATH}"
        ) from exc
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        yield con
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError(
            f"읽기 전용 DB 조회에 실패했습니다: {DB_PATH}"
        ) from exc
    finally:
        con.close()


def _csv_floats(value):
    if not value:
        return []
    return [float(item) for item in value.split(",") if item]


def _csv_ints(value):
    if not value:
        return []
    return [int(item) for item in value.split(",") if item]


def _at(values, index):
    return values[index] if index < len(values) else None


def _meta_error(key, reason):
    raise DatabaseUnavailableError(f"score_meta.{key} 형식이 잘못됐습니다: {reason}")


def _optional_float(value, key):
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        _meta_error(key, "실수가 아닙니다.")


def _optional_int(value, key):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        _meta_error(key, "정수가 아닙니다.")


def _plus(value, extra):
    """NULL 은 NULL 로 둔다 — 모르는 값에 아는 값을 더하면 «안다»가 된다."""
    return None if value is None else value + extra
