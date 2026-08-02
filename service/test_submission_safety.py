"""Regression tests for submission safety boundaries."""

import sqlite3

import pytest

import run as launcher
from service import demo_db, reporting


def test_demo_build_rejects_same_path_without_deleting_source(tmp_path):
    source = tmp_path / "source.db"
    sqlite3.connect(source).close()
    before = source.read_bytes()

    with pytest.raises(ValueError, match="같은 경로"):
        demo_db.build(source, source, verbose=False)

    assert source.read_bytes() == before


def test_demo_build_failure_preserves_existing_output(tmp_path):
    source = tmp_path / "incomplete.db"
    sqlite3.connect(source).close()
    output = tmp_path / "existing.db"
    output.write_bytes(b"existing-output")

    with pytest.raises(RuntimeError, match="원본에 없는 테이블"):
        demo_db.build(source, output, verbose=False)

    assert output.read_bytes() == b"existing-output"


def test_demo_build_reports_missing_input_paths(tmp_path):
    missing_source = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError) as source_error:
        demo_db.build(missing_source, tmp_path / "output.db", verbose=False)
    assert str(missing_source.resolve()) in str(source_error.value)

    source = tmp_path / "source.db"
    sqlite3.connect(source).close()
    missing_parent = tmp_path / "missing" / "output.db"
    with pytest.raises(FileNotFoundError) as output_error:
        demo_db.build(source, missing_parent, verbose=False)
    assert str(missing_parent.parent.resolve()) in str(output_error.value)


def test_demo_audit_scans_nested_runtime_modules(monkeypatch, tmp_path):
    service_dir = tmp_path / "service"
    api_dir = service_dir / "api"
    api_dir.mkdir(parents=True)
    (service_dir / "top.py").write_text(
        'QUERY = "SELECT * FROM grid"\n',
        encoding="utf-8",
    )
    (api_dir / "nested.py").write_text(
        'QUERY = "SELECT * FROM cohort_survival"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(demo_db, "ROOT", tmp_path)

    assert demo_db.referenced_tables(None) == {"grid", "cohort_survival"}


def test_demo_audit_fails_for_declared_but_unused_table(monkeypatch, tmp_path):
    service_dir = tmp_path / "service"
    service_dir.mkdir()
    (service_dir / "empty.py").write_text('"""No SQL."""\n', encoding="utf-8")
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE unused (id INTEGER)")
    monkeypatch.setattr(demo_db, "ROOT", tmp_path)
    monkeypatch.setattr(demo_db, "TABLES", ["unused"])

    assert demo_db.audit(source) == 1


def test_report_rejects_qualitative_claims_without_evidence():
    evidence = {
        "grade": "1",
        "horizonYears": "3",
        "observedSurvivalPercent": "73.1",
    }

    with pytest.raises(reporting.ReportGenerationError):
        reporting.render_evidence_placeholders(
            ["성공 가능성이 높아요.", "앞으로 매출이 성장할 거예요."],
            evidence,
        )


def test_launcher_resolves_relative_db_paths(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    existing = data_dir / "kb.db"
    existing.touch()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KB_DB", "data/kb.db")

    selected = launcher.find_db()

    assert selected == existing.resolve()
    assert launcher.child_env(selected)["KB_DB"] == str(existing.resolve())
    monkeypatch.setenv("KB_DB", "data/new.db")
    assert launcher.db_target() == (data_dir / "new.db").resolve()
