from pipeline.grid import neighbors
from service import alerts

from . import base
from .base import DatabaseUnavailableError
from .cells import RESOLUTION
from .context import REST_EATERY
from .search import _ensure_uptae


def _changes_history(con, grid_id):
    cells = neighbors(grid_id, ring=1)
    cell_slots = ",".join("?" * len(cells))
    rest_slots = ",".join("?" * len(REST_EATERY))
    has_history = con.execute(
        f"SELECT "
        f"EXISTS(SELECT 1 FROM licence WHERE grid_id IN ({cell_slots})) "
        f"OR EXISTS("
        f"  SELECT 1 FROM licence_rest "
        f"  WHERE grid_id IN ({cell_slots}) AND uptae IN ({rest_slots})"
        f")",
        [*cells, *cells, *REST_EATERY],
    ).fetchone()[0]
    if not has_history:
        return None

    run_rows = con.execute(
        "SELECT as_of, MAX(is_current) is_current "
        "FROM score_run WHERE as_of IS NOT NULL "
        "GROUP BY as_of ORDER BY as_of"
    ).fetchall()
    current_as_of = next(
        (row["as_of"] for row in run_rows if row["is_current"]),
        None,
    )
    if current_as_of is None:
        raise DatabaseUnavailableError(
            "현재 채점 판이 없어 개·폐업 이력 기간을 정할 수 없습니다."
        )
    try:
        current_year, current_month = map(int, current_as_of.split("-"))
    except (AttributeError, ValueError):
        raise DatabaseUnavailableError(
            "현재 채점 판의 기준월로 개·폐업 이력 기간을 정할 수 없습니다."
        ) from None
    if not 1 <= current_month <= 12:
        raise DatabaseUnavailableError(
            "현재 채점 판의 기준월로 개·폐업 이력 기간을 정할 수 없습니다."
        )
    current_period = current_year * 2 + (current_month > 6)
    end_period = current_period - 1
    start_period = end_period - 19

    counts = {}
    for table, rest_filter, rest_params in (
        ("licence", "", []),
        (
            "licence_rest",
            f"AND uptae IN ({rest_slots})",
            list(REST_EATERY),
        ),
    ):
        for event, year_column, month_column in (
            ("opened", "open_y", "open_m"),
            ("closed", "close_y", "close_m"),
        ):
            period = (
                f"{year_column} * 2 "
                f"+ CASE WHEN {month_column} <= 6 THEN 0 ELSE 1 END"
            )
            for row in con.execute(
                f"SELECT {year_column} year, "
                f"       CASE WHEN {month_column} <= 6 THEN 1 ELSE 2 END half, "
                f"       COUNT(*) n "
                f"FROM {table} "
                f"WHERE grid_id IN ({cell_slots}) "
                f"  AND {month_column} BETWEEN 1 AND 12 "
                f"  AND ({period}) BETWEEN ? AND ? "
                f"  {rest_filter} "
                f"GROUP BY {year_column}, half",
                [*cells, start_period, end_period, *rest_params],
            ):
                key = (row["year"], row["half"])
                counts.setdefault(key, {"opened": 0, "closed": 0})
                counts[key][event] += row["n"]

    buckets = []
    for period in range(start_period, end_period + 1):
        year, half_index = divmod(period, 2)
        half, first_month, last_month = (
            (1, 1, 6) if half_index == 0 else (2, 7, 12)
        )
        events = counts.get((year, half), {"opened": 0, "closed": 0})
        buckets.append({
            "from": f"{year:04d}-{first_month:02d}",
            "to": f"{year:04d}-{last_month:02d}",
            **events,
        })
    return {
        "unit": RESOLUTION["competition.shopsNeighbor"],
        "bucket_months": 6,
        "buckets": buckets,
        "runs": [{"as_of": row["as_of"]} for row in run_rows],
    }


def grid_changes(grid_id, uptae):
    """이 칸이 직전 채점 판과 견주어 무엇이 달라졌는가.

    견줄 판이 없으면 «변동 없음»이 아니라 available=False 다. 둘을 같은 모양으로
    답하면 사용자는 알림이 도는 줄 알고 기다린다.
    """
    with base.readonly_connection() as con:
        _ensure_uptae(con, uptae)
        history = _changes_history(con, grid_id)
        try:
            return {
                "available": True,
                **alerts.changes_for(con, grid_id, uptae),
                "history": history,
            }
        except alerts.NoBaselineError as exc:
            return {
                "available": False,
                "reason": str(exc),
                "history": history,
            }
