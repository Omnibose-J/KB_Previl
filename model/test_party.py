"""Gate tests for model/party.py.

Run: python -m model.test_party

No network or LLM calls. The tests exercise only quote validation, serving-row
gates, and deterministic district stratification against temporary files.
"""
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from . import party


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def _load_rows(records):
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        full_path = root / "full.jsonl"
        db_path = root / "party.db"
        full_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
            encoding="utf-8",
        )
        original_full_path, original_db_path = party.FULL_PATH, party.DB_PATH
        try:
            party.FULL_PATH, party.DB_PATH = full_path, db_path
            written = party.load(verbose=False)
            con = sqlite3.connect(db_path)
            try:
                rows = con.execute(
                    "SELECT trdar_cd, party, n FROM trdar_party "
                    "ORDER BY trdar_cd, party"
                ).fetchall()
            finally:
                con.close()
        finally:
            party.FULL_PATH, party.DB_PATH = original_full_path, original_db_path
    return written, rows


def _record(cd, label, index):
    return {"trdar_cd": cd, "text": f"글 {index}", "label": label}


@case
def forged_quote_is_voided():
    got = party._clean(
        {"label": "family", "quote": "아이들과 방문"},
        "친절하고 음식이 맛있었다",
    )
    assert got["label"] is None, got
    assert got["void"] == "인용이 원문에 없음", got


@case
def empty_quote_is_voided_with_its_own_reason():
    got = party._clean({"label": "family", "quote": "   "}, "가족과 방문했다")
    assert got["label"] is None, got
    assert got["void"] == "인용 없음", got


@case
def overlong_quote_is_voided_with_its_own_reason():
    quote = "가" * 21
    got = party._clean({"label": "family", "quote": quote}, quote)
    assert got["label"] is None, got
    assert got["void"] == "인용 20자 초과", got


@case
def unknown_class_is_voided_with_its_own_reason():
    got = party._clean({"label": "vendor", "quote": "가족과"}, "가족과 방문했다")
    assert got["label"] is None, got
    assert got["void"] == "라벨 없음", got


@case
def copied_quote_passes_only_the_anti_fabrication_gate():
    got = party._clean(
        {"label": "family", "quote": "음식이 맛있었다"},
        "음식이 맛있었다",
    )
    assert got == {
        "label": "family",
        "quote": "음식이 맛있었다",
        "void": None,
    }, got


@case
def district_below_approved_label_minimum_gets_no_rows():
    records = [
        _record("T-low", "family", i)
        for i in range(party.MIN_POSTS_PER_TRDAR - 1)
    ]
    written, rows = _load_rows(records)
    assert written == 0, written
    assert rows == [], rows


@case
def rejected_classes_never_enter_the_serving_table():
    assert party.APPROVED_CLASSES == ("family", "work")
    labels = ["family"] * 3 + ["work"] * 2
    labels += ["alone", "couple", "friend"] * 2
    written, rows = _load_rows([
        _record("T-approved", label, i) for i, label in enumerate(labels)
    ])
    assert written == 2, written
    assert rows == [
        ("T-approved", "family", 3),
        ("T-approved", "work", 2),
    ], rows


@case
def stratified_targets_fill_the_requested_count():
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "targets.db"
        con = sqlite3.connect(db_path)
        try:
            con.execute(
                "CREATE TABLE trdar_area ("
                "trdar_cd TEXT, trdar_nm TEXT, trdar_se_nm TEXT)"
            )
            rows = [
                ("A1", "골목1", "골목상권"),
                *[(f"B{i}", f"발달{i}", "발달상권") for i in range(1, 5)],
                *[(f"C{i}", f"관광{i}", "관광특구") for i in range(1, 5)],
            ]
            con.executemany("INSERT INTO trdar_area VALUES (?,?,?)", rows)
            con.commit()
        finally:
            con.close()
        original_db_path = party.DB_PATH
        try:
            party.DB_PATH = db_path
            got = party.targets(6)
        finally:
            party.DB_PATH = original_db_path

    assert len(got) == 6, got
    assert len({row[0] for row in got}) == 6, got
    assert {row[2] for row in got} == {"골목상권", "발달상권", "관광특구"}, got


# --- 수집 실패 ≠ 결과 없음 (Codex B-1) -------------------------------------

@case
def fetch_failure_raises_instead_of_returning_empty():
    """빈 리스트로 돌려주면 «검색 결과 없음» 마커가 쓰이고, 그 상권은 재실행에서
    영원히 건너뛰어진다 — 이어받기가 필요한 바로 그 순간에 무너진다."""
    import requests as _rq
    from model import party as P

    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise _rq.RequestException("network down")

    real_get, real_sleep = _rq.get, P.time.sleep
    _rq.get, P.time.sleep = boom, lambda *_: None
    try:
        raised = False
        try:
            P.fetch_posts({"X": "y"}, "테스트상권", tries=2)
        except P.CollectFailed:
            raised = True
        assert raised, "실패가 CollectFailed 로 올라오지 않았다"
        assert calls["n"] == 2, f"재시도 횟수가 다르다: {calls['n']}"
    finally:
        _rq.get, P.time.sleep = real_get, real_sleep


@case
def load_refuses_a_broken_file_before_touching_the_db():
    """깨진 행을 건너뛰고 DELETE 가 돌면, 잘린 파일이 조용히 서빙 테이블을
    줄인다. DB 를 건드리기 전에 실패해야 한다."""
    import tempfile
    import pathlib
    import json as _j
    from model import party as P

    tmp = pathlib.Path(tempfile.mkdtemp())
    bad = tmp / "full.jsonl"
    bad.write_text(
        _j.dumps({"trdar_cd": "A", "trdar_nm": "x", "trdar_se": "골목상권",
                  "text": "t", "label": "family", "quote": "가족과",
                  "void": None}, ensure_ascii=False) + "\n"
        + '{"trdar_cd": "B", "text": "잘린',
        encoding="utf-8")
    real = P.FULL_PATH
    P.FULL_PATH = bad
    try:
        failed = False
        try:
            P.load(verbose=False)
        except RuntimeError as exc:
            failed = "2행" in str(exc) and "건드리지 않았다" in str(exc)
        assert failed, "깨진 파일을 조용히 넘어갔거나 행 번호를 알려주지 않았다"
    finally:
        P.FULL_PATH = real


def main():
    failed = 0
    for fn in CASES:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {exc}")
    total = len(CASES)
    print(f"\nparty 게이트 {total - failed}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
