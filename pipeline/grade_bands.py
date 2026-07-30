"""Shared grade segmentation for serving and offline analysis."""

from itertools import accumulate

import numpy as np


# Fixed school-grade-shaped shares selected before inspecting the final
# holdout outcomes.
SHARE = (
    0.04,
    0.07,
    0.12,
    0.17,
    0.20,
    0.17,
    0.12,
    0.07,
    0.04,
)

GRADE_COUNT = len(SHARE)
GRADE_BAND_LABELS = ("1등급", "중간 (2~8등급)", "9등급")


def grade_segments(order):
    """Split a descending score order at cumulative fixed-share boundaries."""
    n = len(order)
    stops = [min(n, round(n * share)) for share in accumulate(SHARE)]
    stops[-1] = n
    starts = [0, *stops[:-1]]
    segments = tuple(order[start:stop] for start, stop in zip(starts, stops))
    if any(len(segment) == 0 for segment in segments):
        raise ValueError(
            f"등급을 {GRADE_COUNT}개 만들기에는 홀드아웃 표본이 부족합니다."
        )
    return segments


def grade_edges(scores):
    """Return descending-score lower bounds for the fixed grade shares."""
    values = np.asarray(scores)
    order = np.argsort(-values)
    return tuple(float(values[segment].min()) for segment in grade_segments(order))


def grade_numbers(scores, edges=None):
    """Assign equal scores to one grade instead of splitting a tied cohort."""
    boundaries = grade_edges(scores) if edges is None else tuple(edges)
    if len(boundaries) != GRADE_COUNT:
        raise ValueError(f"등급 경계는 {GRADE_COUNT}개여야 합니다.")
    return np.array(
        [
            next(
                (
                    grade
                    for grade, boundary in enumerate(boundaries, 1)
                    if score >= boundary
                ),
                GRADE_COUNT,
            )
            for score in scores
        ],
        dtype=int,
    )
