"""Behavioral tests for the shared grade segmentation contract."""

from model.backtest import grades
from pipeline.grade_bands import (
    GRADE_BAND_LABELS,
    GRADE_COUNT,
    SHARE,
    grade_edges,
    grade_numbers,
    grade_segments,
)


def test_fixed_school_nine_grade_shares_and_labels():
    assert SHARE == (
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
    assert GRADE_COUNT == 9
    assert GRADE_BAND_LABELS == ("1등급", "중간 (2~8등급)", "9등급")


def test_holdout_segments_cover_every_row_once_at_fixed_boundaries():
    segments = grade_segments(tuple(range(7_915)))

    assert [len(segment) for segment in segments] == [
        317,
        554,
        949,
        1_346,
        1_583,
        1_346,
        949,
        554,
        317,
    ]
    assert tuple(index for segment in segments for index in segment) == tuple(
        range(7_915)
    )


def test_too_small_holdout_fails_instead_of_silently_dropping_a_grade():
    try:
        grade_segments(tuple(range(10)))
    except ValueError as exc:
        assert "표본이 부족" in str(exc)
    else:
        raise AssertionError("빈 등급을 허용했습니다.")


def test_equal_scores_are_not_split_across_grades():
    scores = [1.0] * 100

    assert set(grade_numbers(scores, grade_edges(scores))) == {1}


def test_wrong_edge_count_is_rejected():
    try:
        grade_numbers([0.5], [0.5] * (GRADE_COUNT + 1))
    except ValueError as exc:
        assert f"{GRADE_COUNT}개" in str(exc)
    else:
        raise AssertionError("등급 수와 다른 경계 배열을 허용했습니다.")


def test_backtest_does_not_split_a_tied_boundary_across_served_grades():
    scores = [1 - index / 100 for index in range(100)]
    scores[4] = scores[3]

    rows = grades([index % 2 for index in range(100)], scores)

    assert rows[0][1] == 5
    assert rows[1][1] == 6
