"""Building outlines for one cell, proxied live from the VWORLD data API.

`kb.db` 에 굽지 않는다. 실측으로 칸 하나에 건물이 28~94 개라 채점된 20,148 칸을
전부 담으면 폴리곤이 100 만 개를 넘고, 255MB 제출용 DB 에 들어가지 않는다.
그래서 화면이 실제로 여는 칸만 그때 물어본다.

**표기 전용이다.** 점수·등급·추천 순위 어디에도 들어가지 않는다.
"""

import threading
from collections import OrderedDict

import httpx

from pipeline.config import load_env
from service import api


SOURCE = "vworld"
ENDPOINT = "https://api.vworld.kr/req/data"
# 수치지도 건물. 건물명·지상층수·건물관리번호를 폴리곤과 같이 준다.
LAYER = "LT_C_SPBD"
# 브이월드는 키에 등록된 도메인을 검증한다. 서버 호출에는 Referer 가 없어서
# 이 값을 명시하지 않으면 «인증키 정보가 올바르지 않습니다» 가 돌아온다 —
# 키가 아니라 도메인 문제인데 문구가 키를 가리켜서 한 번 오진했다.
DOMAIN = "127.0.0.1"
TIMEOUT_S = 6.0
# 실측 최대가 한 칸 94 개였다. 상한을 두는 것은 상류가 이상한 범위를 물었을 때
# 응답이 무한정 커지지 않게 하려는 것이고, 정상 칸은 여기 걸리지 않는다.
MAX_BUILDINGS = 300
CACHE_SIZE = 128


class FootprintsUnavailableError(RuntimeError):
    """상류(VWORLD)를 부르지 못했다. 우리 DB 가 없는 것과 구분한다."""


_cache = OrderedDict()
_cache_lock = threading.Lock()


def _api_key():
    key = (load_env().get("VWORLD_API_KEY") or "").strip()
    if not key:
        raise FootprintsUnavailableError(
            "VWORLD_API_KEY 가 없어 건물 윤곽선을 가져올 수 없습니다."
        )
    return key


def _bbox(polygon):
    lons = [point[0] for point in polygon]
    lats = [point[1] for point in polygon]
    return min(lons), min(lats), max(lons), max(lats)


def _outer_rings(geometry):
    """바깥 링만 남긴다. 화면은 건물 외곽선만 그리므로 안뜰(구멍)은 버린다."""
    kind = (geometry or {}).get("type")
    coordinates = (geometry or {}).get("coordinates") or []
    if kind == "MultiPolygon":
        return [polygon[0] for polygon in coordinates if polygon]
    if kind == "Polygon":
        return [coordinates[0]] if coordinates else []
    return []


def _floors(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _building(feature):
    props = feature.get("properties") or {}
    rings = _outer_rings(feature.get("geometry"))
    if not rings:
        return None
    name = (props.get("buld_nm") or props.get("buld_nm_dc") or "").strip()
    return {
        "name": name or None,
        "floors": _floors(props.get("gro_flo_co")),
        "rings": rings,
    }


def _fetch(grid_id):
    west, south, east, north = _bbox(api.grid_polygon(grid_id))
    params = {
        "service": "data",
        "request": "GetFeature",
        "data": LAYER,
        "key": _api_key(),
        "domain": DOMAIN,
        "format": "json",
        "size": MAX_BUILDINGS,
        "geometry": "true",
        "crs": "EPSG:4326",
        "geomFilter": f"BOX({west},{south},{east},{north})",
    }
    try:
        response = httpx.get(ENDPOINT, params=params, timeout=TIMEOUT_S)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise FootprintsUnavailableError(
            f"VWORLD 응답을 받지 못했습니다: {type(exc).__name__}"
        ) from exc

    body = payload.get("response") or {}
    status = body.get("status")
    # NOT_FOUND 는 실패가 아니라 «그 범위에 건물이 없다» 는 정상 답이다.
    if status == "NOT_FOUND":
        return []
    if status != "OK":
        detail = ((body.get("error") or {}).get("text")) or status or "알 수 없는 응답"
        raise FootprintsUnavailableError(f"VWORLD 가 거절했습니다: {detail}")

    collection = ((body.get("result") or {}).get("featureCollection")) or {}
    buildings = (_building(feature) for feature in collection.get("features") or [])
    return [item for item in buildings if item is not None]


def for_grid(grid_id):
    with _cache_lock:
        cached = _cache.get(grid_id)
        if cached is not None:
            _cache.move_to_end(grid_id)
    if cached is not None:
        return {**cached, "cached": True}

    with api.base.readonly_connection() as con:
        known = con.execute(
            "SELECT 1 FROM grid WHERE grid_id = ?", (grid_id,)
        ).fetchone()
    if known is None:
        raise api.ResourceNotFoundError(f"알 수 없는 격자입니다: {grid_id}")

    result = {"gridId": grid_id, "source": SOURCE, "buildings": _fetch(grid_id)}
    with _cache_lock:
        _cache[grid_id] = result
        if len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return {**result, "cached": False}
