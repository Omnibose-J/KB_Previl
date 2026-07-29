"""격자 변동 판정 검정.

실제 kb.db 가 아니라 손으로 만든 작은 DB 를 쓴다 — 분류 규칙을 재려면 «두 판이
이렇게 다를 때» 를 마음대로 만들 수 있어야 하는데, 배치를 두 번 돌려서는
경계 조건(표본 부족·미세 이동·재보정)을 만들 수 없다.
"""

import sqlite3

import pytest

from service import alerts

SCHEMA = """
CREATE TABLE grid_score (uptae TEXT, grid_id TEXT, score REAL, grade INTEGER,
                         observed REAL, PRIMARY KEY (uptae, grid_id));
CREATE TABLE grid_score_prev (run_id TEXT, uptae TEXT, grid_id TEXT, score REAL,
                              grade INTEGER, observed REAL,
                              PRIMARY KEY (run_id, uptae, grid_id));
CREATE TABLE score_run (run_id TEXT PRIMARY KEY, as_of TEXT, model TEXT,
                        train_years TEXT, features_hash TEXT, is_current INTEGER);
CREATE TABLE grid_feature (grid_id TEXT PRIMARY KEY, survive_3y_n INTEGER);
"""

OLD, NEW = "2026-01-gbm-aaaa", "2026-07-gbm-aaaa"


def _db(
    *,
    old_grade=3,
    new_grade=1,
    old_score=0.30,
    new_score=0.50,
    sample=200,
    new_features="aaaa",
    new_model="gbm",
    scored_before=True,
    scored_now=True,
):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute("INSERT INTO grid_feature VALUES ('1_1', ?)", (sample,))
    con.execute(
        "INSERT INTO score_run VALUES (?,?,?,?,?,?)",
        (OLD, "2026-01", "gbm", "2005,2006", "aaaa", 0),
    )
    con.execute(
        "INSERT INTO score_run VALUES (?,?,?,?,?,?)",
        (NEW, "2026-07", new_model, "2005,2006", new_features, 1),
    )
    if scored_before:
        con.execute(
            "INSERT INTO grid_score_prev VALUES (?,?,?,?,?,?)",
            (OLD, "한식", "1_1", old_score, old_grade, 0.6),
        )
    if scored_now:
        con.execute(
            "INSERT INTO grid_score VALUES (?,?,?,?,?)",
            ("한식", "1_1", new_score, new_grade, 0.77),
        )
    return con


def _diff(**kw):
    return alerts.diff_cell(_db(**kw), "1_1", "한식", OLD)


def test_grade_move_on_the_same_ruler_is_a_real_change():
    event = _diff()
    assert event["kind"] == "grade"
    assert (event["before_grade"], event["after_grade"]) == (3, 1)
    assert "3등급에서 1등급으로 올랐어요" in alerts.sentence(event)


def test_same_grade_reports_nothing():
    assert _diff(old_grade=2, new_grade=2) is None


@pytest.mark.parametrize(
    "changed", [{"new_features": "bbbb"}, {"new_model": "rf"}]
)
def test_a_changed_ruler_is_recalibration_not_a_worse_location(changed):
    """모델·피처가 바뀐 판의 등급 차이를 «등급 하락»으로 알리면 거짓이다.

    사용자의 자리는 그대로이고 우리가 자를 바꾼 것이다. 문장도 그렇게 말해야
    한다 — 등급 숫자만 던지면 둘이 구분되지 않는다.
    """
    event = _diff(old_grade=1, new_grade=4, **changed)
    assert event["kind"] == "recalibration"
    assert "이 자리가 변한 게 아니라" in alerts.sentence(event)


def test_a_grade_flip_without_a_real_score_move_is_boundary_noise():
    """등급이 두 칸 움직여도 점수가 등급 폭만큼 못 갔으면 경계에 걸쳐 있던 것이다."""
    assert _diff(old_grade=3, new_grade=1, old_score=0.4000, new_score=0.4001) is None


def test_a_single_grade_step_is_within_normal_six_month_drift():
    """실측으로 20,117격자 중 11,688(58%)이 6개월에 등급 1칸을 움직인다.

    보통 칸의 점수 이동(중앙값 0.0174)이 등급 폭(중앙값 0.0285)의 61% 라서,
    1칸 변동은 «자리가 변했다»가 아니라 «라벨 경계를 스쳤다»에 가깝다. 전부
    알리면 알림이 곧 소음이 된다.
    """
    assert _diff(old_grade=3, new_grade=2, old_score=0.30, new_score=0.50) is None
    assert _diff(old_grade=3, new_grade=1, old_score=0.30, new_score=0.50) is not None


def test_a_thin_neighbourhood_does_not_raise_grade_alerts():
    """이웃 이력이 얇으면 한두 곳의 개·폐업으로 등급이 튄다."""
    assert _diff(sample=10) is None
    assert _diff(sample=200) is not None  # 표본만이 차이임을 보인다


def test_entering_and_leaving_the_scored_set_are_their_own_kinds():
    """«평가 불가 -> 평가됨»은 등급이 좋아진 것이 아니다."""
    entered = alerts.diff_cell(_db(scored_before=False), "1_1", "한식", OLD)
    assert entered["kind"] == "became_scorable"
    assert "평가할 수 있게 됐어요" in alerts.sentence(entered)

    left = alerts.diff_cell(_db(scored_now=False), "1_1", "한식", OLD)
    assert left["kind"] == "became_unscorable"
    assert "평가하지 않아요" in alerts.sentence(left)


def test_a_missing_baseline_is_an_error_not_a_silent_empty():
    """첫 배치 직후에는 견줄 판이 없다. 조용히 «변동 없음»으로 답하면
    사용자는 알림이 도는 줄 알고 기다린다."""
    con = _db()
    con.execute("DELETE FROM score_run WHERE run_id = ?", (OLD,))
    with pytest.raises(alerts.NoBaselineError):
        alerts.diff_cell(con, "1_1", "한식", OLD)

    con = _db()
    con.execute("UPDATE score_run SET is_current = 0")
    with pytest.raises(alerts.NoBaselineError):
        alerts.diff_cell(con, "1_1", "한식", OLD)
