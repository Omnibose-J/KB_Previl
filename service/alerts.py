"""격자 변동 판정 — 두 채점 판을 견주어 «무엇이 달라졌는지» 분류한다.

읽기 전용이다. 발송은 하지 않는다. 이벤트를 «만드는 것»과 «보내는 것»은
실패 방식이 달라서(전자는 데이터 문제, 후자는 전송 문제) 한 함수에 두면
메일 서버가 죽었을 때 판정까지 못 하게 된다.

핵심은 «변동»이 한 종류가 아니라는 것이다.

  competition   반경 안에서 같은 업태가 열거나 닫았다. 등급은 그대로일 수 있다.
  grade         그 자리의 등급이 달라졌다.
  recalibration 모델·학습창·피처가 바뀌어 «전부» 다시 매겨졌다.

세 번째를 두 번째로 세면 «당신 자리가 나빠졌습니다»라는 거짓 알림이 나간다.
사용자의 자리는 그대로인데 우리가 자를 바꾼 것이기 때문이다. score_run 이
그 구분을 위해 존재한다.
"""

# 임계값은 실측으로 정했다(2026-01 -> 2026-07, 한식 20,117격자, 같은 적합).
#
#   등급 폭 중앙값  0.0285 (중간 등급 0.018~0.033)   |점수 이동| 0.0174 (p90 0.0531)
#
# 보통 칸이 6개월에 등급 폭의 61% 를 움직인다. 그래서 «1칸 변동»이 20,117 중
# 11,688(58%)에서 일어나고, 전부 알리면 알림이 소음이 된다.
#
# 두 조건을 함께 요구한다: 등급 2칸 이상 + 점수도 등급 폭 하나 이상. 실측에서
# 2칸 이상은 3,584건이고 |점수 이동| 중앙값 0.0488 로 드리프트와 갈린다.
MIN_SCORE_SHIFT = 0.0285
MIN_GRADE_STEPS = 2

# 이웃 이력이 얇은 칸은 한두 곳의 개·폐업으로 등급이 튄다. 채점 자체가
# MIN_RING_HISTORY=20 을 요구하므로 그 두 배를 하한으로 둔다. 실제로 걸러지는
# 건수는 많지 않다(등급 이동 건의 표본 중앙값이 141) — 위 두 조건이 주 필터이고
# 이것은 극단만 막는 바닥이다.
MIN_SAMPLE = 40


class NoBaselineError(LookupError):
    """견줄 이전 판이 없다. 첫 배치 직후가 그렇다."""


def _run(con, run_id):
    row = con.execute(
        "SELECT run_id, as_of, model, train_years, features_hash, is_current "
        "FROM score_run WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise NoBaselineError(f"score_run 에 {run_id} 가 없습니다.")
    return row


def current_run(con):
    row = con.execute(
        "SELECT run_id FROM score_run WHERE is_current = 1"
    ).fetchone()
    if row is None:
        raise NoBaselineError("현재 판(score_run.is_current=1)이 없습니다.")
    return row["run_id"]


def is_recalibration(before, after):
    """두 판 사이에 «자»가 바뀌었는가.

    셋 중 하나라도 다르면 등급 비교가 같은 척도 위에 있지 않다. 그 판의 등급
    차이는 자리의 변화로 셀 수 없다 — 전부 재보정이다.
    """
    return (
        before["model"] != after["model"]
        or before["train_years"] != after["train_years"]
        or before["features_hash"] != after["features_hash"]
    )


def baseline_run(con):
    """견줄 «이전 판». 현재판이 아닌 것 중 가장 최근 as_of.

    없으면 NoBaselineError 다 — 첫 배치 직후가 그렇다. 빈 목록으로 답하면
    사용자는 «변동이 없다»로 읽지만 사실은 «아직 잴 수 없다»이다.
    """
    row = con.execute(
        "SELECT run_id FROM score_run WHERE is_current = 0 "
        "ORDER BY as_of DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise NoBaselineError("견줄 이전 채점 판이 없습니다.")
    return row["run_id"]


def changes_for(con, grid_id, uptae):
    """한 칸의 변동을 조회용 모양으로. 알릴 것이 없으면 event=None."""
    before = baseline_run(con)
    event = diff_cell(con, grid_id, uptae, before)
    return {
        "baseline_run": before,
        "current_run": current_run(con),
        "baseline_as_of": _run(con, before)["as_of"],
        "current_as_of": _run(con, current_run(con))["as_of"],
        "event": event,
        "sentence": sentence(event) if event else None,
    }


def diff_cell(con, grid_id, uptae, before_run, after_run=None):
    """한 칸의 변동을 분류한다. 알릴 것이 없으면 None.

    after_run 을 안 주면 현재 판과 견준다.
    """
    after_run = after_run or current_run(con)
    before, after = _run(con, before_run), _run(con, after_run)

    old = con.execute(
        "SELECT score, grade FROM grid_score_prev "
        "WHERE run_id = ? AND uptae = ? AND grid_id = ?",
        (before_run, uptae, grid_id),
    ).fetchone()
    new = con.execute(
        "SELECT score, grade FROM grid_score WHERE uptae = ? AND grid_id = ?",
        (uptae, grid_id),
    ).fetchone()

    # 평가 대상에 들고 나는 것도 변동이다. 다만 «등급이 나빠졌다»가 아니라
    # «이제 평가할 수 있게 됐다/없게 됐다»라서 따로 부른다.
    if old is None and new is None:
        return None
    if old is None:
        return _event("became_scorable", grid_id, uptae, before, after, None, new)
    if new is None:
        return _event("became_unscorable", grid_id, uptae, before, after, old, None)

    if old["grade"] == new["grade"]:
        return None
    if is_recalibration(before, after):
        return _event("recalibration", grid_id, uptae, before, after, old, new)
    if abs(new["grade"] - old["grade"]) < MIN_GRADE_STEPS:
        return None  # 1칸은 6개월 정상 드리프트 안이다
    if abs(new["score"] - old["score"]) < MIN_SCORE_SHIFT:
        return None  # 등급 폭 하나도 못 움직였다 — 경계에 걸쳐 있었을 뿐이다
    if _sample(con, grid_id) < MIN_SAMPLE:
        return None  # 표본이 얇아 한두 곳으로 튄다

    return _event("grade", grid_id, uptae, before, after, old, new)


def _sample(con, grid_id):
    row = con.execute(
        "SELECT survive_3y_n FROM grid_feature WHERE grid_id = ?", (grid_id,)
    ).fetchone()
    return (row["survive_3y_n"] or 0) if row else 0


def _event(kind, grid_id, uptae, before, after, old, new):
    return {
        "kind": kind,
        "grid_id": grid_id,
        "uptae": uptae,
        "before_run": before["run_id"],
        "after_run": after["run_id"],
        "before_as_of": before["as_of"],
        "after_as_of": after["as_of"],
        "before_grade": old["grade"] if old else None,
        "after_grade": new["grade"] if new else None,
        "score_shift": (new["score"] - old["score"]) if old and new else None,
    }


# 문장은 종류마다 «무엇이 변한 것인지»를 먼저 말한다. 등급 숫자만 던지면
# 재보정과 자리 변화가 사용자에게 똑같이 읽힌다.
def sentence(event):
    uptae, before, after = event["uptae"], event["before_as_of"], event["after_as_of"]
    if event["kind"] == "recalibration":
        return (
            f"이 자리가 변한 게 아니라 저희 기준이 바뀌었어요. "
            f"{uptae} 등급이 {event['before_grade']}등급에서 "
            f"{event['after_grade']}등급으로 다시 매겨졌습니다 ({before} → {after})."
        )
    if event["kind"] == "became_scorable":
        return (
            f"주변 기록이 쌓여 이 자리를 평가할 수 있게 됐어요. "
            f"{uptae} {event['after_grade']}등급입니다 ({after} 기준)."
        )
    if event["kind"] == "became_unscorable":
        return (
            f"주변 기록이 부족해져 이 자리는 당분간 평가하지 않아요 "
            f"({after} 기준)."
        )
    direction = "올랐어요" if event["after_grade"] < event["before_grade"] else "내렸어요"
    return (
        f"{uptae} 등급이 {event['before_grade']}등급에서 "
        f"{event['after_grade']}등급으로 {direction} ({before} → {after})."
    )
