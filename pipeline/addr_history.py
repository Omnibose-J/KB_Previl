"""Build and audit address-level tenancy chains from licence observations."""

import argparse
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from itertools import groupby
import json
import re
import sqlite3
import sys

from .config import DB_PATH


LABEL_POLICY = (
    "<=3 months=true; 4-5 months=excluded(null); "
    ">=6 months=false; no successor=false"
)
TIME_BASIS = "month (월 단위 approximation from open_y/open_m and close_y/close_m)"
FLOOR_POLICY = (
    "Preserve observed floor tokens; never infer or allocate a floor when the "
    "source address has none."
)

TABLE_SQL = """
CREATE TABLE addr_tenancy (
  mgtno                  TEXT PRIMARY KEY,
  addr                   TEXT NOT NULL,
  uptae                  TEXT NOT NULL,
  seq                    INTEGER NOT NULL,
  open_ym                INTEGER NOT NULL,
  close_ym               INTEGER,
  tenure_months          INTEGER,
  successor_mgtno        TEXT,
  vacancy_months_after   INTEGER,
  succeeded              INTEGER CHECK (succeeded IN (0, 1) OR succeeded IS NULL)
)
"""

_NUMBERED_FLOOR = re.compile(
    r"(?:지하|지상)?\s*\d{1,3}(?:\s*[,~\-]\s*\d{1,3})*\s*층"
)
_B_FLOOR = re.compile(r"(?:^|\s)([Bb]\d+)")


@dataclass(frozen=True)
class SourceTenancy:
    mgtno: str
    addr: str
    uptae: str
    open_y: int
    open_m: int
    close_y: int | None
    close_m: int | None
    is_closed: int


def _month_index(year, month):
    return year * 12 + month - 1


def _ym(year, month):
    return year * 100 + month


def _evaluate_group(group):
    ordered = sorted(
        group,
        key=lambda row: (row.open_y, row.open_m, row.mgtno),
    )
    opens = [
        (_month_index(row.open_y, row.open_m), row.mgtno, row)
        for row in ordered
    ]
    open_keys = [(month, mgtno) for month, mgtno, _row in opens]
    output = []

    for seq, row in enumerate(ordered, start=1):
        open_month = _month_index(row.open_y, row.open_m)
        close_month = (
            _month_index(row.close_y, row.close_m)
            if row.close_y is not None and row.close_m is not None
            else None
        )
        tenure = None
        successor = None
        vacancy = None
        succeeded = None

        if row.is_closed and close_month is not None and close_month >= open_month:
            tenure = close_month - open_month
            position = bisect_left(open_keys, (close_month, ""))
            while position < len(opens):
                candidate_month, candidate_mgtno, _candidate = opens[position]
                if candidate_mgtno != row.mgtno:
                    successor = candidate_mgtno
                    vacancy = candidate_month - close_month
                    break
                position += 1

            # 월 단위 label: <=3=True, 4-5=NULL, >=6=False, no successor=False.
            if successor is None:
                succeeded = 0
            elif vacancy <= 3:
                succeeded = 1
            elif vacancy >= 6:
                succeeded = 0

        output.append(
            (
                row.mgtno,
                row.addr,
                row.uptae,
                seq,
                _ym(row.open_y, row.open_m),
                _ym(row.close_y, row.close_m)
                if row.close_y is not None and row.close_m is not None
                else None,
                tenure,
                successor,
                vacancy,
                succeeded,
            )
        )
    return output


def _source_rows(con):
    rows = con.execute(
        "SELECT mgtno, addr, uptae, open_y, open_m, close_y, close_m, is_closed "
        "FROM licence "
        "WHERE addr <> '' AND open_y IS NOT NULL AND open_m IS NOT NULL "
        "ORDER BY addr, uptae, open_y, open_m, mgtno"
    )
    for row in rows:
        yield SourceTenancy(*row)


def build():
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("DROP TABLE IF EXISTS addr_tenancy")
        con.execute(TABLE_SQL)

        inserted = 0
        batch = []
        for _key, group in groupby(
            _source_rows(con),
            key=lambda row: (row.addr, row.uptae),
        ):
            batch.extend(_evaluate_group(list(group)))
            if len(batch) >= 20_000:
                con.executemany(
                    "INSERT INTO addr_tenancy VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                inserted += len(batch)
                batch.clear()
        if batch:
            con.executemany(
                "INSERT INTO addr_tenancy VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            inserted += len(batch)

        con.execute(
            "CREATE UNIQUE INDEX ix_addr_tenancy_chain "
            "ON addr_tenancy(addr, uptae, seq)"
        )
        con.execute(
            "CREATE INDEX ix_addr_tenancy_label ON addr_tenancy(succeeded)"
        )
        con.executemany(
            "INSERT OR REPLACE INTO score_meta(k, v) VALUES (?, ?)",
            (
                ("addr_tenancy_grain", "licence addr x uptae"),
                ("addr_tenancy_time_basis", TIME_BASIS),
                ("addr_tenancy_label_policy", LABEL_POLICY),
                ("addr_tenancy_floor_policy", FLOOR_POLICY),
            ),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    print(f"addr_tenancy 생성: {inserted:,}행")
    print(f"시간 기준: {TIME_BASIS}")
    print(f"라벨 정책: {LABEL_POLICY}")


def _readonly_connection():
    uri = f"{DB_PATH.resolve().as_uri()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def _pure_selftest():
    group = [
        SourceTenancy("a", "addr", "uptae", 2024, 1, 2024, 3, 1),
        SourceTenancy("b", "addr", "uptae", 2024, 5, 2024, 6, 1),
        SourceTenancy("c", "addr", "uptae", 2024, 10, 2024, 11, 1),
        SourceTenancy("d", "addr", "uptae", 2025, 5, 2025, 6, 1),
    ]
    rows = {row[0]: row for row in _evaluate_group(group)}
    assert rows["a"][6:] == (2, "b", 2, 1)
    assert rows["b"][6:] == (1, "c", 4, None)
    assert rows["c"][6:] == (1, "d", 6, 0)
    assert rows["d"][6:] == (1, None, None, 0)

    active = SourceTenancy("active", "other", "uptae", 2025, 1, None, None, 0)
    assert _evaluate_group([active])[0][6:] == (None, None, None, None)

    invalid = SourceTenancy("invalid", "third", "uptae", 2025, 6, 2025, 5, 1)
    assert _evaluate_group([invalid])[0][6:] == (None, None, None, None)


def selftest():
    _pure_selftest()
    con = _readonly_connection()
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            )
        }
        assert "addr_tenancy" in tables, "addr_tenancy table is missing; run --build"

        expected = con.execute(
            "SELECT COUNT(*) FROM licence "
            "WHERE addr <> '' AND open_y IS NOT NULL AND open_m IS NOT NULL"
        ).fetchone()[0]
        actual = con.execute("SELECT COUNT(*) FROM addr_tenancy").fetchone()[0]
        assert actual == expected, (actual, expected)

        broken_chains = con.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT addr, uptae, COUNT(*) n, MIN(seq) first_seq, "
            "MAX(seq) last_seq, COUNT(DISTINCT seq) distinct_seq "
            "FROM addr_tenancy GROUP BY addr, uptae "
            "HAVING first_seq <> 1 OR last_seq <> n OR distinct_seq <> n)"
        ).fetchone()[0]
        assert broken_chains == 0

        bad_labels = con.execute(
            "SELECT SUM(CASE WHEN "
            "(close_ym IS NULL AND tenure_months IS NULL "
            " AND successor_mgtno IS NULL AND vacancy_months_after IS NULL "
            " AND succeeded IS NULL) OR "
            "(close_ym IS NOT NULL AND tenure_months IS NULL "
            " AND successor_mgtno IS NULL AND vacancy_months_after IS NULL "
            " AND succeeded IS NULL) OR "
            "(close_ym IS NOT NULL AND tenure_months IS NOT NULL "
            " AND successor_mgtno IS NULL AND vacancy_months_after IS NULL "
            " AND succeeded IS 0) OR "
            "(close_ym IS NOT NULL AND tenure_months IS NOT NULL "
            " AND successor_mgtno IS NOT NULL "
            " AND vacancy_months_after IS NOT NULL "
            " AND vacancy_months_after BETWEEN 0 AND 3 AND succeeded IS 1) OR "
            "(close_ym IS NOT NULL AND tenure_months IS NOT NULL "
            " AND successor_mgtno IS NOT NULL "
            " AND vacancy_months_after IS NOT NULL "
            " AND vacancy_months_after IN (4, 5) AND succeeded IS NULL) OR "
            "(close_ym IS NOT NULL AND tenure_months IS NOT NULL "
            " AND successor_mgtno IS NOT NULL "
            " AND vacancy_months_after IS NOT NULL "
            " AND vacancy_months_after >= 6 AND succeeded IS 0) "
            "THEN 0 ELSE 1 END) FROM addr_tenancy"
        ).fetchone()[0]
        assert bad_labels == 0

        metadata = dict(
            con.execute(
                "SELECT k, v FROM score_meta WHERE k IN "
                "('addr_tenancy_time_basis', 'addr_tenancy_label_policy')"
            )
        )
        assert metadata["addr_tenancy_time_basis"] == TIME_BASIS
        assert metadata["addr_tenancy_label_policy"] == LABEL_POLICY
        assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"

        counts = dict(
            con.execute(
                "SELECT COALESCE(CAST(succeeded AS TEXT), 'excluded_or_unobserved'), "
                "COUNT(*) FROM addr_tenancy GROUP BY succeeded"
            )
        )
    finally:
        con.close()

    print(f"selftest PASS: {actual:,}행, chain 오류 0, label 오류 0")
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


def _floor_parts(addr):
    marker = _NUMBERED_FLOOR.search(addr)
    if marker:
        token = re.sub(r"\s+", "", marker.group(0))
        return addr[: marker.start()].rstrip(" ,"), token

    for word, token in (("지하", "지하"), ("지상", "지상")):
        position = addr.find(word)
        if position >= 0:
            return addr[:position].rstrip(" ,"), token

    marker = _B_FLOOR.search(addr)
    if marker:
        return addr[: marker.start(1)].rstrip(" ,"), marker.group(1).upper()

    if "층" in addr:
        position = addr.find("층")
        return addr[:position].rstrip(" ,"), "층"
    return None, None


def _label_counts(groups):
    counts = defaultdict(int)
    for group in groups.values():
        for row in _evaluate_group(group):
            close_ym, tenure, vacancy, succeeded = row[5], row[6], row[8], row[9]
            if close_ym is None or tenure is None:
                counts["unobserved"] += 1
            elif succeeded is None and vacancy in (4, 5):
                counts["excluded"] += 1
            elif succeeded == 1:
                counts["positive"] += 1
            else:
                counts["negative"] += 1
    labelled = counts["positive"] + counts["negative"]
    counts["labelled"] = labelled
    counts["rate"] = counts["positive"] / labelled if labelled else None
    return dict(counts)


def floor_impact():
    con = _readonly_connection()
    try:
        total = con.execute("SELECT COUNT(*) FROM licence").fetchone()[0]
        rows = [
            SourceTenancy(*row)
            for row in con.execute(
                "SELECT mgtno, addr, uptae, open_y, open_m, "
                "close_y, close_m, is_closed FROM licence "
                "WHERE addr <> '' AND open_y IS NOT NULL AND open_m IS NOT NULL "
                "AND (addr LIKE '%층%' OR addr LIKE '%지하%' OR addr LIKE '%지상%' "
                "OR addr GLOB '* B[0-9]*' OR addr GLOB '* b[0-9]*')"
            )
        ]
    finally:
        con.close()

    without_floor = defaultdict(list)
    with_floor = defaultdict(list)
    for row in rows:
        base_addr, floor_token = _floor_parts(row.addr)
        assert base_addr is not None and floor_token is not None
        without_floor[(base_addr, row.uptae)].append(row)
        with_floor[(base_addr, row.uptae, floor_token)].append(row)

    unsplit = _label_counts(without_floor)
    split = _label_counts(with_floor)
    delta_pp = (split["rate"] - unsplit["rate"]) * 100
    result = {
        "floor_token_rows": len(rows),
        "all_rows": total,
        "floor_token_percent": len(rows) / total * 100,
        "without_floor_split": unsplit,
        "with_floor_split": split,
        "rate_difference_pp": delta_pp,
        "policy": FLOOR_POLICY,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def diff_legacy():
    con = _readonly_connection()
    try:
        row = con.execute(
            "SELECT "
            "SUM(CASE WHEN t.succeeded=1 THEN 1 ELSE 0 END) new_positive, "
            "SUM(CASE WHEN l.succession_suspect=1 THEN 1 ELSE 0 END) legacy_positive, "
            "SUM(CASE WHEN t.succeeded=1 AND l.succession_suspect=1 THEN 1 ELSE 0 END) both_positive, "
            "SUM(CASE WHEN t.succeeded=1 AND l.succession_suspect=0 THEN 1 ELSE 0 END) new_only, "
            "SUM(CASE WHEN (t.succeeded IS NULL OR t.succeeded=0) "
            "AND l.succession_suspect=1 THEN 1 ELSE 0 END) legacy_only "
            "FROM addr_tenancy t JOIN licence l USING(mgtno)"
        ).fetchone()
    finally:
        con.close()

    keys = (
        "new_positive",
        "legacy_positive",
        "both_positive",
        "new_only",
        "legacy_only",
    )
    print(json.dumps(dict(zip(keys, row)), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--build", action="store_true")
    actions.add_argument("--selftest", action="store_true")
    actions.add_argument("--floor-impact", action="store_true")
    actions.add_argument("--diff-legacy", action="store_true")
    args = parser.parse_args()

    if args.build:
        build()
    elif args.selftest:
        selftest()
    elif args.floor_impact:
        floor_impact()
    else:
        diff_legacy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
