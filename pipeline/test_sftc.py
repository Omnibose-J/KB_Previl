"""Gate tests for pipeline/sftc.py — the checksum is the only thing standing
between a misread digit and a published comparison.

Run: python -m pipeline.test_sftc

No network and no vision calls. What is under test is `verify_rows`: whether a
row that does not add up is kept out, and whether a row that does add up comes
through unmodified. Everything upstream (board scrape, rendering) fails loudly
on its own; this is the step that could fail quietly.
"""
import sys

from .sftc import (TRDAR_TOL, UPTAE_TOL, _dedupe, agree, classify,
                   median_from_bands, verify_rows)


def _trdar(total, deposit, goodwill, fitout, name="테스트상권"):
    return {"gu": "테스트구", "trdar": name, "total": total, "deposit": deposit,
            "goodwill": goodwill, "fitout": fitout, "page": 1}


def _uptae(bands, mean=1000.0, name="테스트업종"):
    return {"uptae": name, "bands": list(bands), "mean": mean, "page": 1}


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# --- district table: 계 = 보증금 + 권리금 + 시설투자비 --------------------

@case
def exact_row_is_accepted():
    acc, rej = verify_rows([_trdar(10000, 4000, 4000, 2000)], "trdar")
    assert len(acc) == 1 and not rej, (acc, rej)


@case
def misread_goodwill_is_rejected():
    """The failure this whole module exists to catch: one column misread while
    the other three are right. It cannot pass, because the total disagrees."""
    acc, rej = verify_rows([_trdar(10000, 4000, 4900, 2000)], "trdar")
    assert not acc, f"검산이 통과시켰다: {acc}"
    assert len(rej) == 1 and "검산 불일치" in rej[0]["reason"], rej


@case
def rounding_slack_is_honoured_but_bounded():
    inside = _trdar(10000, 4000, 4000, 2001)          # +1
    outside = _trdar(10000, 4000, 4000, 2002)         # +2
    acc, rej = verify_rows([inside, outside], "trdar")
    assert len(acc) == 1 and acc[0]["fitout"] == 2001, acc
    assert len(rej) == 1 and rej[0]["fitout"] == 2002, rej
    assert TRDAR_TOL == 1.0


@case
def accepted_values_are_not_rewritten():
    """A repaired row is indistinguishable from a correct one downstream, so the
    gate must pass values through untouched."""
    row = _trdar(25595, 10257, 10225, 5113, name="가로수길")
    acc, _ = verify_rows([row], "trdar")
    assert len(acc) == 1
    for k in ("total", "deposit", "goodwill", "fitout", "trdar"):
        assert acc[0][k] == row[k], (k, acc[0][k], row[k])


@case
def real_2023_row_satisfies_the_printed_checksum():
    """Measured on the 2023 edition p.27: the printed total equals the sum of
    the three columns exactly. If a future edition stops doing this the gate
    would reject everything, and this test says where to look."""
    rows = [_trdar(25595, 10257, 10225, 5113, "가로수길"),
            _trdar(12634, 4364, 5836, 2434, "강남구청역"),
            _trdar(7893, 4548, 2230, 1115, "대치역")]
    acc, rej = verify_rows(rows, "trdar")
    assert len(acc) == 3 and not rej, rej


@case
def missing_column_is_rejected_not_crashed():
    bad = {"trdar": "결손", "total": 10000, "deposit": 4000, "page": 1}
    acc, rej = verify_rows([bad], "trdar")
    assert not acc and len(rej) == 1 and "결손" in rej[0]["reason"], rej


@case
def non_numeric_is_rejected_not_crashed():
    acc, rej = verify_rows([_trdar(10000, 4000, "四千", 2000)], "trdar")
    assert not acc and len(rej) == 1, (acc, rej)


# --- industry table: 구간 백분율 합 = 100 ---------------------------------

@case
def bands_summing_to_100_are_accepted():
    acc, rej = verify_rows([_uptae([23.2, 22.1, 21.2, 10.1, 5.2, 18.2])], "uptae")
    assert len(acc) == 1 and not rej, rej


@case
def bands_missing_mass_are_rejected():
    """A dropped band reads as a plausible distribution but is not one."""
    acc, rej = verify_rows([_uptae([23.2, 22.1, 21.2, 10.1, 5.2, 12.0])], "uptae")
    assert not acc and len(rej) == 1, (acc, rej)


@case
def wrong_band_count_is_rejected():
    acc, rej = verify_rows([_uptae([25.0, 25.0, 25.0, 25.0])], "uptae")
    assert not acc, acc
    assert UPTAE_TOL == 0.3


@case
def one_decimal_rounding_is_honoured():
    acc, _ = verify_rows([_uptae([28.8, 22.7, 19.4, 9.8, 5.8, 13.6])], "uptae")
    assert len(acc) == 1, "합 100.1 은 한 자리 반올림 범위 안이다"


@case
def rejected_rows_never_leak_into_accepted():
    rows = [_trdar(10000, 4000, 4000, 2000, "정상"),
            _trdar(10000, 4000, 9000, 2000, "오독"),
            _trdar(8000, 3000, 3000, 2000, "정상2")]
    acc, rej = verify_rows(rows, "trdar")
    names = {r["trdar"] for r in acc}
    assert names == {"정상", "정상2"}, names
    assert {r["trdar"] for r in rej} == {"오독"}
    assert len(acc) + len(rej) == len(rows), "행이 사라지거나 늘었다"


# --- page classification: model transcribes, code decides -----------------

@case
def district_page_is_classified_by_its_row_labels():
    """2023 p.27 / 2022 p.44 — headers carry 권리금, labels are place names."""
    got = classify(["구역", "상권", "계", "보증금", "권리금", "시설투자비"],
                   ["가로수길", "강남구청역", "강남역"])
    assert got == "trdar", got


@case
def industry_page_is_classified_by_its_row_labels():
    """2022 p.57 — the 계 row comes first, so more than one label must be read.

    Its columns are money bands, not 권리금; only the caption names the measure.
    A headers-only check would miss this page entirely."""
    headers = ["업종", "2천만원 미만", "1억원 이상", "평균"]
    labels = ["계", "한식음식점", "외국식음식점"]
    assert classify(headers, labels, "업종별 권리금") == "uptae"
    assert classify(headers, labels, "") is None, "제목 없이 잡히면 안 된다"


@case
def page_without_a_goodwill_column_is_not_a_hit():
    """Editions discuss 권리금 in prose and headline sentences; only a column
    counts, or the extractor gets pointed at a page with no table to read."""
    assert classify(["구역", "상권", "계", "보증금", "월세"],
                    ["가로수길", "강남역"]) is None
    assert classify([], []) is None
    assert classify(None, None) is None


@case
def goodwill_column_with_unreadable_labels_defaults_to_district():
    """Unlabelled rows fall to trdar because every edition has a district table
    and only some have an industry one — the wrong prompt is caught downstream
    by the checksum, an unlocated table is not caught at all."""
    assert classify(["상권", "계", "권리금"], []) == "trdar"


# --- fabrication: what the checksum cannot see ----------------------------

@case
def a_fabricated_but_self_consistent_row_passes_the_checksum():
    """Measured on the 2023 edition: p.27 produced rows for districts that are
    not printed on p.27, and they added up. This asserts the weakness exists so
    nobody later mistakes the checksum for a fabrication check."""
    invented = _trdar(13670, 4011, 5762, 3897, "뚝섬역")
    acc, rej = verify_rows([invented], "trdar")
    assert len(acc) == 1 and not rej, "검산만으로는 지어낸 행을 못 거른다"


@case
def agreement_across_passes_drops_the_fabricated_row():
    real = _trdar(10000, 4000, 4000, 2000, "실제상권")
    run_a = [real, _trdar(13670, 4011, 5762, 3897, "지어낸상권")]
    run_b = [real, _trdar(12500, 3800, 5300, 3400, "지어낸상권")]
    stable, drifted = agree([run_a, run_b], "trdar")
    assert [r["trdar"] for r in stable] == ["실제상권"], stable
    assert [r["trdar"] for r in drifted] == ["지어낸상권"], drifted


@case
def a_row_only_one_pass_saw_is_not_stable():
    real = _trdar(10000, 4000, 4000, 2000, "양쪽")
    only_once = _trdar(8000, 3000, 3000, 2000, "한쪽")
    stable, drifted = agree([[real, only_once], [real]], "trdar")
    assert [r["trdar"] for r in stable] == ["양쪽"], stable
    assert drifted and drifted[0]["reason"] == "재추출에 없음", drifted


@case
def a_row_only_the_second_pass_saw_is_reported_not_kept():
    real = _trdar(10000, 4000, 4000, 2000, "양쪽")
    late = _trdar(8000, 3000, 3000, 2000, "늦게등장")
    stable, drifted = agree([[real], [real, late]], "trdar")
    assert [r["trdar"] for r in stable] == ["양쪽"], stable
    assert [r["trdar"] for r in drifted] == ["늦게등장"], drifted


@case
def industry_agreement_compares_bands_too():
    a = _uptae([23.2, 22.1, 21.2, 10.1, 5.2, 18.2], 6165.4, "한식음식점")
    b = _uptae([23.2, 22.1, 21.2, 10.1, 5.2, 18.2], 6165.4, "한식음식점")
    c = _uptae([23.2, 22.1, 21.2, 10.1, 5.2, 18.2], 6165.9, "한식음식점")
    assert len(agree([[a], [b]], "uptae")[0]) == 1
    assert len(agree([[a], [c]], "uptae")[0]) == 0, "평균이 다르면 일치가 아니다"


@case
def a_conflicting_repeat_drops_every_copy():
    """The 2023 run read 수유역 twice with identical numbers but under two
    different districts. Nothing in the data says which district is real."""
    a = _trdar(12045, 3403, 4762, 3880, "수유역")
    b = {**_trdar(12045, 3403, 4762, 3880, "수유역"), "gu": "금천구"}
    rows = [a, b, _trdar(10000, 4000, 4000, 2000, "고유상권")]
    kept, dupes = _dedupe(rows, "trdar")
    assert [r["trdar"] for r in kept] == ["고유상권"], kept
    assert len(dupes) == 2 and "불일치" in dupes[0]["reason"], dupes


@case
def an_identical_repeat_is_merged_not_dropped():
    """Slice overlap makes the same printed row appear twice. Two reads that
    agree on every field corroborate each other — dropping both would throw away
    a verified row to punish the crop geometry."""
    row = _trdar(12045, 3403, 4762, 3880, "수유역")
    kept, dupes = _dedupe([row, dict(row)], "trdar")
    assert len(kept) == 1 and not dupes, (kept, dupes)
    assert kept[0]["goodwill"] == 4762


# --- published median: the headline mean is not comparable ----------------

@case
def median_lands_in_the_band_that_crosses_fifty():
    """한식 2022: cumulative 23.2, 45.3, 66.5 — the median is 4.7 points into
    the 4,000~6,000 band, which is 21.2 points wide."""
    got = median_from_bands([23.2, 22.1, 21.2, 10.1, 5.2, 18.2])
    assert abs(got - (4000 + 4.7 / 21.2 * 2000)) < 1, got
    assert 4400 < got < 4500, got


@case
def median_is_well_below_the_published_mean():
    """Goodwill is right-tailed: the same industry's published mean is 6,165.4
    against a median near 4,443. Comparing our median to their mean would charge
    the estimate for a skew it does not model."""
    assert median_from_bands([23.2, 22.1, 21.2, 10.1, 5.2, 18.2]) < 6165.4


@case
def a_first_band_over_fifty_gives_a_median_inside_it():
    got = median_from_bands([60.0, 20.0, 10.0, 5.0, 3.0, 2.0])
    assert abs(got - (50.0 / 60.0 * 2000)) < 1, got


@case
def open_top_band_returns_none_rather_than_a_guess():
    """If the median sits in 「1억원 이상」 there is no upper edge to interpolate
    against, and inventing one would put a made-up number in the control."""
    assert median_from_bands([5.0, 5.0, 5.0, 5.0, 5.0, 75.0]) is None


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
    print(f"\n검산 게이트 {total - failed}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
