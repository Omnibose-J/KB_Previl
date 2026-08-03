"""공정위 창업비용 힌트 — 로더 계약과 인제스트 가드.

두 가지를 지킨다:
  1. 로더: 파일 없음 = 빈 힌트(정상 답), 손상 = 예외(침묵 금지).
  2. 인제스트 가드: 원천 필드 오배치(합 항등식)와 커피/음료 함정이
     회귀하면 여기서 먼저 터진다.
"""

import json

import pytest

from service import runway_params

# 인제스트 스크립트(scripts/)와 패키징(tools/)은 출하본에 없다 — 그 대상을
# 재는 테스트만 각자 importorskip 으로 감싼다. 로더 계약 테스트는 출하본에서도
# 그대로 돈다(감사 게이트가 벗겨낸 트리에서 pytest 를 돌린다).


def test_loader_missing_file_yields_empty_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(
        runway_params, "UPFRONT_HELPER_PATH", tmp_path / "absent.json"
    )
    assert runway_params.upfront_helper() == {}


def test_loader_corrupt_file_raises(monkeypatch, tmp_path):
    broken = tmp_path / "franchise_costs.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(runway_params, "UPFRONT_HELPER_PATH", broken)
    with pytest.raises(ValueError):
        runway_params.upfront_helper()


def test_loader_shapes_shipped_file():
    """저장소에 실린 실데이터 — 12업태 전부, 값은 만원 상식 범위, 라벨은
    근거·연도·제외 범위를 말한다."""
    hints = runway_params.upfront_helper()
    assert set(hints) == {
        "한식", "까페", "분식", "통닭(치킨)", "호프/통닭", "정종/대포집/소주방",
        "일식", "중국식", "경양식", "외국음식전문점(인도,태국등)",
        "식육(숯불구이)", "기타",
    }
    for hint in hints.values():
        assert 500 <= hint["value"] <= 50_000  # 만원
        assert "공정위" in hint["label"] and "제외" in hint["label"]
        assert str(hint["year"]) in hint["label"]
    assert hints["정종/대포집/소주방"]["proxy"] is True
    assert hints["까페"]["proxy"] is False


def test_identity_guard_catches_field_meaning_change():
    fc = pytest.importorskip("scripts.franchise_costs")
    rows = [dict(r) for r in fc.SAMPLE_2024] * 2
    fc.validate_rows(rows)  # 실측 픽스처는 통과
    rows[0]["frcsCnt"] = 12  # «진짜 count» 가 된 세상 — 합이 무너진다
    with pytest.raises(SystemExit):
        fc.validate_rows(rows)


def test_cafe_maps_to_coffee_not_beverages():
    """부분일치였다면 «음료 (커피 외)» 에 걸렸을 함정의 고정."""
    fc = pytest.importorskip("scripts.franchise_costs")
    helper, _ = fc.map_rows([dict(r) for r in fc.SAMPLE_2024])
    assert helper["까페"]["sourceIndustry"] == "커피"
    # 헬퍼 합에 보증금(frcsCnt)이 섞이지 않는다
    assert helper["까페"]["value"] == 109 + 86 + 2544


def test_meta_serves_upfront_helper_camelcase():
    """/api/meta 가 upfrontHelper 를 UpfrontHint 형태로 싣는다."""
    from fastapi.testclient import TestClient

    from service.app import app

    with TestClient(app) as client:
        payload = client.get("/api/meta").json()
    hints = payload["upfrontHelper"]
    assert isinstance(hints, dict) and "한식" in hints
    row = hints["한식"]
    assert set(row) == {"value", "year", "label", "proxy"}


def test_shipped_json_matches_loader_source():
    """manifest 가 싣는 파일이 로더가 읽는 바로 그 경로다."""
    manifest = pytest.importorskip("tools.manifest")

    arcs = {arc for _src, arc in manifest.SHIP_FILES}
    assert "service/data/franchise_costs.json" in arcs
    raw = json.loads(
        runway_params.UPFRONT_HELPER_PATH.read_text(encoding="utf-8")
    )
    assert raw["unit"] == "만원"
