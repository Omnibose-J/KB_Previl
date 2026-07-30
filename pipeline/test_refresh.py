"""Regression tests for source-cache refresh propagation."""

import json
from types import SimpleNamespace

from pipeline import bootstrap, collect, seoul_api


class _Connection:
    def close(self):
        pass


def test_bootstrap_collect_forwards_refresh_force(monkeypatch):
    seen = []

    monkeypatch.setattr(
        collect,
        "collect_seoul",
        lambda quarter, force=False: seen.append((quarter, force)),
    )
    monkeypatch.setattr(bootstrap, "load_env", lambda: {})

    bootstrap._collect(SimpleNamespace(quarter="2025_1", force=True))

    assert seen == [("2025_1", True)]


def test_collect_force_reaches_every_seoul_fetch(monkeypatch):
    calls = []

    def fake_fetch_all(service, **kwargs):
        calls.append((service, kwargs))
        return []

    monkeypatch.setattr(collect, "fetch_all", fake_fetch_all)

    collect.collect_seoul(force=True)

    assert len(calls) == 7
    assert all(kwargs["force"] is True for _, kwargs in calls)


def test_fetch_all_force_bypasses_existing_complete_and_partial_cache(
    monkeypatch, tmp_path
):
    cache = tmp_path / "licence.jsonl"
    partial = tmp_path / "licence.partial"
    cache.write_text('{"version":"old"}\n', encoding="utf-8")
    partial.write_text('{"version":"partial-old"}\n', encoding="utf-8")
    calls = []

    def fake_get(service, start, end, args=""):
        calls.append((service, start, end, args))
        return 1, [{"version": "fresh"}]

    monkeypatch.setattr(seoul_api, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(seoul_api, "init", _Connection)
    monkeypatch.setattr(seoul_api, "_get", fake_get)
    monkeypatch.setattr(seoul_api, "_record", lambda *_args: None)
    monkeypatch.setattr(seoul_api, "remaining", lambda: 1_000)

    rows = seoul_api.fetch_all("Service", cache_name="licence", force=True)

    assert rows == [{"version": "fresh"}]
    assert calls == [("Service", 1, seoul_api.SEOUL_PAGE, "")]
    assert [
        json.loads(line)
        for line in cache.read_text(encoding="utf-8").splitlines()
    ] == rows
    assert not partial.exists()


def test_fetch_all_without_force_reuses_existing_cache(monkeypatch, tmp_path):
    cache = tmp_path / "licence.jsonl"
    cache.write_text('{"version":"cached"}\n', encoding="utf-8")

    monkeypatch.setattr(seoul_api, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        seoul_api,
        "_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("HTTP path must not run")
        ),
    )

    assert seoul_api.fetch_all("Service", cache_name="licence") == [
        {"version": "cached"}
    ]
