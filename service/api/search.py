from pipeline.config import SEOUL_BBOX
from pipeline.grid import in_seoul, to_grid_id

from . import base
from .base import ApiInputError, DatabaseUnavailableError, MAX_GRID_CELLS, ViewportTooLargeError
from .cells import GRID_SELECT, RESOLUTION, _grid_cell, _grid_detail
from .context import _concept_mix_batch, _party_batch, _rest_food_batch, _sales_mix_batch, _same_uptae_batch, _uptae_sales_batch
from .meta import _district_names


def _ensure_uptae(con, uptae):
    if not con.execute("SELECT 1 FROM grid_score LIMIT 1").fetchone():
        raise DatabaseUnavailableError("배치 미실행: grid_score가 비어 있습니다.")
    found = con.execute(
        "SELECT 1 FROM grid_score WHERE uptae = ? LIMIT 1", (uptae,)
    ).fetchone()
    if not found:
        raise ApiInputError("지원하지 않는 업태입니다.")


def _ensure_districts(con, districts):
    if not districts:
        return
    known = _district_names(
        row[0]
        for row in con.execute(
            "SELECT DISTINCT sgis_adm_nm FROM grid_sgis WHERE sgis_adm_nm IS NOT NULL"
        )
    )
    unknown = sorted(set(districts) - set(known))
    if unknown:
        raise ApiInputError("지원하지 않는 자치구입니다: " + ", ".join(unknown))


def _district_filter(districts):
    cleaned = list(dict.fromkeys(value.strip() for value in districts if value.strip()))
    if not cleaned:
        return "", [], cleaned
    clause = " AND (" + " OR ".join("gs.sgis_adm_nm LIKE ?" for _ in cleaned) + ")"
    return clause, [f"% {district} %" for district in cleaned], cleaned


def recommend(uptae, districts=(), top=24):
    district_sql, district_args, cleaned = _district_filter(districts)
    with base.readonly_connection() as con:
        _ensure_uptae(con, uptae)
        _ensure_districts(con, cleaned)
        total_grids = con.execute(
            "SELECT COUNT(*) FROM grid_score WHERE uptae = ?", (uptae,)
        ).fetchone()[0]
        in_scope = con.execute(
            "SELECT COUNT(*) FROM grid_score s "
            "LEFT JOIN grid_sgis gs ON gs.grid_id = s.grid_id "
            "WHERE s.uptae = ?" + district_sql,
            [uptae, *district_args],
        ).fetchone()[0]
        rows = con.execute(
            GRID_SELECT
            + " WHERE 1 = 1"
            + district_sql
            + " ORDER BY s.score DESC, s.grid_id LIMIT ?",
            [uptae, *district_args, top],
        ).fetchall()
        grid_ids = [row["grid_id"] for row in rows]
        mix = _concept_mix_batch(con, grid_ids)
        party = _party_batch(con, grid_ids)
        same = _same_uptae_batch(con, grid_ids, uptae)
        rest = _rest_food_batch(con, grid_ids)
        usales = _uptae_sales_batch(con, grid_ids, uptae)

    items = []
    for row in rows:
        item = _grid_detail(row, uptae, same[row["grid_id"]],
                            rest[row["grid_id"]], usales[row["grid_id"]])
        item["concept_mix"] = mix.get(row["grid_id"])
        item["visitor_party"] = party.get(row["grid_id"])
        items.append(item)

    return {
        "uptae": uptae,
        "districts": cleaned,
        "total_grids": total_grids,
        "in_scope": in_scope,
        "count": len(rows),
        "items": items,
        "resolutions": RESOLUTION,
    }


def grid_detail(grid_id, uptae):
    with base.readonly_connection() as con:
        _ensure_uptae(con, uptae)
        row = con.execute(
            GRID_SELECT + " WHERE f.grid_id = ?", (uptae, grid_id)
        ).fetchone()
        if row is None:
            return None
        mix = _concept_mix_batch(con, [grid_id])
        party = _party_batch(con, [grid_id])
        smix = _sales_mix_batch(con, [grid_id])
        same = _same_uptae_batch(con, [grid_id], uptae)
        rest = _rest_food_batch(con, [grid_id])
        usales = _uptae_sales_batch(con, [grid_id], uptae)
    item = _grid_detail(row, uptae, same[grid_id], rest[grid_id], usales[grid_id])
    item["concept_mix"] = mix.get(grid_id)
    item["visitor_party"] = party.get(grid_id)
    item["sales_mix"] = smix.get(grid_id)
    return item


def at_point(lon, lat, uptae):
    if not in_seoul(lon, lat):
        raise ApiInputError("서울 범위의 WGS84 좌표를 입력해 주세요.")
    return grid_detail(to_grid_id(lon, lat), uptae)


def grids(uptae, bbox, max_cells=MAX_GRID_CELLS):
    lon_min, lat_min, lon_max, lat_max = bbox
    if lon_min >= lon_max or lat_min >= lat_max:
        raise ApiInputError("bbox는 lon_min,lat_min,lon_max,lat_max 순서여야 합니다.")
    # 뷰포트가 서울보다 넓은 것은 잘못된 입력이 아니라 «줌아웃»이다. 예전엔 네
    # 귀퉁이가 전부 서울 안이어야 해서, 지도를 조금만 넓게 열면 화면에 날 것의
    # 422 가 떴다(2026-08-03 실사고). 서울과의 교집합으로 좁혀서 답하고, 겹치는
    # 데가 아예 없을 때만 거절한다 — 너무 넓으면 아래 413 이 «확대하세요»로 받는다.
    seoul_lon_min, seoul_lat_min, seoul_lon_max, seoul_lat_max = SEOUL_BBOX
    lon_min, lat_min = max(lon_min, seoul_lon_min), max(lat_min, seoul_lat_min)
    lon_max, lat_max = min(lon_max, seoul_lon_max), min(lat_max, seoul_lat_max)
    if lon_min >= lon_max or lat_min >= lat_max:
        raise ApiInputError("서울과 겹치는 범위가 없습니다. 서울 안에서 찾아 주세요.")

    with base.readonly_connection() as con:
        _ensure_uptae(con, uptae)
        rows = con.execute(
            GRID_SELECT
            + " WHERE f.center_lon BETWEEN ? AND ?"
            + " AND f.center_lat BETWEEN ? AND ?"
            + " ORDER BY f.grid_id LIMIT ?",
            (uptae, lon_min, lon_max, lat_min, lat_max, max_cells + 1),
        ).fetchall()

    if len(rows) > max_cells:
        raise ViewportTooLargeError(max_cells)
    return {
        "count": len(rows),
        "max_cells": max_cells,
        "items": [_grid_cell(row, uptae) for row in rows],
        "resolutions": {
            "grade": "격자 100m",
            "observedSurvival": "등급별 홀드아웃 실측",
            "salesAvailable": "상권 포함 여부",
        },
    }
