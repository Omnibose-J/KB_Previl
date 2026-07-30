"""Regression tests for licence-aware split-cache invalidation."""

import sqlite3

from model import cache, evaluate


def _database():
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE licence ("
        "mgtno TEXT PRIMARY KEY, is_closed INTEGER, open_y INTEGER, "
        "open_m INTEGER, "
        "close_y INTEGER, close_m INTEGER)"
    )
    con.execute(
        "INSERT INTO licence VALUES ('A', 0, 2023, 1, NULL, NULL)"
    )
    con.commit()
    return con


def _record_builds(monkeypatch):
    builds = []

    def fake_load_split(*_args, **_kwargs):
        builds.append(len(builds) + 1)
        return {"build": builds[-1]}

    monkeypatch.setattr(evaluate, "load_split", fake_load_split)
    return builds


def _split(con):
    return cache.cached_split(con, [2005], [2023], horizon=3)


def test_result_only_licence_change_invalidates_cached_split(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    builds = _record_builds(monkeypatch)
    con = _database()
    try:
        first = _split(con)
        con.execute(
            "UPDATE licence SET is_closed=1, close_y=2024, close_m=7 "
            "WHERE mgtno='A'"
        )
        con.commit()
        second = _split(con)
    finally:
        con.close()

    assert first != second
    assert builds == [1, 2]


def test_licence_row_count_change_invalidates_cached_split(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    builds = _record_builds(monkeypatch)
    con = _database()
    try:
        first = _split(con)
        con.execute(
            "INSERT INTO licence VALUES ('B', 0, 2024, 1, NULL, NULL)"
        )
        con.commit()
        second = _split(con)
    finally:
        con.close()

    assert first != second
    assert builds == [1, 2]


def test_unchanged_licence_reuses_cached_split(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    builds = _record_builds(monkeypatch)
    con = _database()
    try:
        first = _split(con)
        second = _split(con)
    finally:
        con.close()

    assert first == second
    assert builds == [1]


def test_roc_visualization_uses_shared_data_fingerprinted_path(
    monkeypatch, tmp_path
):
    from scripts import roc_viz

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    builds = _record_builds(monkeypatch)
    con = _database()
    expected = _split(con)
    monkeypatch.setattr(roc_viz, "connect_ro", lambda: con)

    got = roc_viz.require_split([2005], [2023], horizon=3)

    assert got == expected
    assert builds == [1]
