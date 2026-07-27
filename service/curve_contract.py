"""Storage contract for batch-computed grade survival curves."""

import json
import math


CURVE_GRADES = tuple(range(1, 11))
CURVE_MONTHS = 36
CURVE_KEY = "survival_curves_36m"


def _validate_curve(curve):
    if len(curve) != CURVE_MONTHS + 1:
        raise ValueError("each curve must contain months 0..36")
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in curve):
        raise ValueError("curve values must be finite rates in 0..1")
    if any(left < right for left, right in zip(curve, curve[1:])):
        raise ValueError("survival curves must be non-increasing")


def serialize_curve_payload(
    curves,
    sample_sizes,
    rank_model,
    rank_features,
    train_years,
    test_years,
):
    if set(curves) != set(CURVE_GRADES):
        raise ValueError("curves for grades 1..10 are required")
    if set(sample_sizes) != set(CURVE_GRADES):
        raise ValueError("sample sizes for grades 1..10 are required")
    rows = []
    for grade in CURVE_GRADES:
        curve = list(curves[grade])
        _validate_curve(curve)
        if not isinstance(sample_sizes[grade], int) or sample_sizes[grade] <= 0:
            raise ValueError("sample sizes must be positive integers")
        rows.append(
            {
                "grade": grade,
                "n": sample_sizes[grade],
                "survival": [round(value, 8) for value in curve],
            }
        )
    payload = {
        "rankModel": rank_model,
        "rankFeatures": list(rank_features),
        "trainYears": list(train_years),
        "testYears": list(test_years),
        "horizonMonths": CURVE_MONTHS,
        "curves": rows,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_curve_payload(
    value,
    expected_model,
    expected_features,
    expected_train_years,
    expected_test_years,
):
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("curve payload must be JSON") from exc
    if payload.get("rankModel") != expected_model:
        raise ValueError("curve rankModel does not match score_meta")
    if payload.get("rankFeatures") != list(expected_features):
        raise ValueError("curve rankFeatures do not match score_meta")
    if payload.get("trainYears") != list(expected_train_years):
        raise ValueError("curve trainYears do not match score_meta")
    if payload.get("testYears") != list(expected_test_years):
        raise ValueError("curve testYears do not match score_meta")
    if payload.get("horizonMonths") != CURVE_MONTHS:
        raise ValueError("curve horizon must be 36 months")

    rows = payload.get("curves")
    if not isinstance(rows, list) or len(rows) != len(CURVE_GRADES):
        raise ValueError("ten grade rows are required")
    curves = {}
    for row in rows:
        try:
            grade = int(row["grade"])
            sample_size = int(row["n"])
            curve = [float(value) for value in row["survival"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("curve values must be numeric") from exc
        if grade in curves or grade not in CURVE_GRADES:
            raise ValueError("curve grades must be unique values in 1..10")
        if sample_size <= 0:
            raise ValueError("curve sample sizes must be positive")
        _validate_curve(curve)
        curves[grade] = curve
    if set(curves) != set(CURVE_GRADES):
        raise ValueError("curves for grades 1..10 are required")
    return curves
