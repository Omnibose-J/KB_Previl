"""Building-level facts derived only from restaurant licence records."""

import re
from collections import Counter

from service import api


SOURCE = "licence"
MAX_BUILDINGS = 50
JIBUN_PATTERN = re.compile(
    r"^(서울특별시\s+\S+구\s+\S+동?\s+(?:산\s*)?\d+(?:-\d+)?)"
)
BUBUN_TAIL = re.compile(r"-\d+$")
CITY_PREFIX = "서울특별시 "


def _parse_address(address):
    if not address:
        return None
    match = JIBUN_PATTERN.match(address)
    if match is None:
        return None

    jibun = " ".join(match.group(1).split())
    building_name = address[match.end() :].split(",", 1)[0].strip() or None
    return jibun, building_name


def _most_frequent(values):
    if not values:
        return None
    return min(values, key=lambda value: (-values[value], value))


def address_for_grid(grid_id):
    """지도에서 짚은 칸이 «어디»인지 답하는 대략 주소.

    100m 칸은 여러 번지에 걸치므로 한 점을 특정할 수 없다. 부번을 떼고 본번까지만
    모아 가장 많은 것을 쓰고, 이름에 «일대»를 붙여 그 폭을 밝힌다.
    """
    with api.base.readonly_connection() as con:
        row = con.execute(
            "SELECT gs.sgis_adm_nm FROM grid g "
            "LEFT JOIN grid_sgis gs ON gs.grid_id = g.grid_id "
            "WHERE g.grid_id = ?",
            (grid_id,),
        ).fetchone()
        if row is None:
            raise api.ResourceNotFoundError(f"알 수 없는 격자입니다: {grid_id}")
        addresses = [
            r["addr"]
            for r in con.execute(
                "SELECT addr FROM licence WHERE grid_id = ?", (grid_id,)
            )
        ]

    district, adm_dong = api.location_names(row["sgis_adm_nm"])
    bonbun = Counter()
    for address in addresses:
        parsed = _parse_address(address)
        if parsed is not None:
            bonbun[BUBUN_TAIL.sub("", parsed[0])] += 1

    jibun = _most_frequent(bonbun)
    if jibun is not None:
        short = jibun.removeprefix(CITY_PREFIX)
        return {
            "grid_id": grid_id,
            "district": district,
            "adm_dong": adm_dong,
            "jibun": short,
            "label": f"{short} 일대",
            "precision": "jibun",
            "records": sum(bonbun.values()),
            "agree": bonbun[jibun],
        }

    # 인허가 기록이 없는 칸(채점 격자의 5.1%). 행정동은 실제로 아는 값이므로
    # 번지를 지어내지 않고 그 단위로 답한다.
    label = " ".join(part for part in (district, adm_dong) if part) or None
    return {
        "grid_id": grid_id,
        "district": district,
        "adm_dong": adm_dong,
        "jibun": None,
        "label": label,
        "precision": "dong" if label else None,
        "records": 0,
        "agree": 0,
    }


def for_grid(grid_id):
    with api.base.readonly_connection() as con:
        known = con.execute(
            "SELECT 1 FROM grid WHERE grid_id = ?",
            (grid_id,),
        ).fetchone()
        if known is None:
            raise api.ResourceNotFoundError(f"알 수 없는 격자입니다: {grid_id}")

        rows = con.execute(
            "SELECT addr, uptae, is_closed "
            "FROM licence WHERE grid_id = ?",
            (grid_id,),
        ).fetchall()

    groups = {}
    unparsed_count = 0
    for row in rows:
        parsed = _parse_address(row["addr"])
        if parsed is None:
            unparsed_count += 1
            continue

        jibun, building_name = parsed
        group = groups.setdefault(
            jibun,
            {
                "building_names": Counter(),
                "active_shops": 0,
                "openings_total": 0,
                "closures_total": 0,
                "uptae_mix": Counter(),
            },
        )
        group["openings_total"] += 1
        if building_name is not None:
            group["building_names"][building_name] += 1
        if row["is_closed"] == 1:
            group["closures_total"] += 1
        elif row["is_closed"] == 0:
            group["active_shops"] += 1
            group["uptae_mix"][row["uptae"]] += 1

    buildings = []
    for jibun, group in groups.items():
        uptae_mix = sorted(
            group["uptae_mix"].items(),
            key=lambda item: (-item[1], item[0] is None, item[0] or ""),
        )[:3]
        buildings.append(
            {
                "jibun": jibun,
                "building_name": _most_frequent(group["building_names"]),
                "active_shops": group["active_shops"],
                "openings_total": group["openings_total"],
                "closures_total": group["closures_total"],
                "uptae_mix": [
                    {"uptae": uptae, "active": active}
                    for uptae, active in uptae_mix
                ],
            }
        )

    buildings.sort(key=lambda item: (-item["active_shops"], item["jibun"]))
    return {
        "grid_id": grid_id,
        "source": SOURCE,
        "buildings": buildings[:MAX_BUILDINGS],
        "unparsed_count": unparsed_count,
    }
