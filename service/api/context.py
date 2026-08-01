import json

from pipeline.config import FOOD_INDUTY, REST_EATERY_UPTAE, UPTAE_INDUTY
from pipeline.grid import neighbors


# 까페만 다른 표에서 센다. `licence` 는 일반음식점만 담고 카페는 대부분
# 휴게음식점으로 인허가돼, 영업 중 1,239곳으로 보이던 것이 실제로는 14,366곳
# 이었다(창업자가 보던 경쟁 수가 실제의 9%).
#
# 다른 열한 업태는 손대지 않는다. 통닭(치킨)은 누락이 아니라 분류 경계 차이라
# (인허가 10,435 vs 상가업소 7,849) 다른 원천을 붙이면 없던 오차가 들어간다.
# 휴게음식점을 쓰는 이유도 «더 많아서»가 아니라 같은 인허가 계열이라 개·폐업
# 시점과 좌표계 처리가 `licence` 와 같기 때문이다 — SEMAS 상가업소는 21,619곳
# 으로 더 크지만 개·폐업 이력이 없어 «영업 중»의 정의부터 다르다.
REST_UPTAE = {
    "까페": ("커피숍", "다방", "전통찻집", "떡카페", "키즈카페"),
}

# «영업 중인 음식점»에 함께 세는 휴게음식점. 서울 영업 중 음식업 131,153곳 중
# 22,108곳(16.9%)이 여기 있는데 화면은 일반음식점 109,045곳만 세고 있었다.
# 집합은 pipeline.config 가 정한다 — model.concept_mix 도 같은 것을 써야
# «음식점 수»와 «주변에 많은 가게»가 같은 모집단을 말한다.
REST_EATERY = REST_EATERY_UPTAE


def _same_uptae_batch(con, grid_ids, uptae):
    """업태별 «영업 중» 점포 수 — 이 칸과 3x3 링.

    `competitor_same_uptae`(json: 업태 -> 수)는 그 칸의 전수 집계이고 합이
    `food_store_cnt` 와 전 격자에서 일치한다. 그래서 키가 없으면 «모름»이 아니라
    진짜 0 이다. 링 합은 `food_store_cnt_r1` 과 같은 정의(중심 포함 3x3)를 쓰고,
    이웃 중 `grid_feature` 에 없는 칸은 데이터가 닿지 않은 칸이라 합에서 빠진다
    (0 으로 채우지 않는다).

    까페만 `licence_rest` 에서 센다(REST_UPTAE 참조). 두 경로 다 «그 업태로
    인허가된 영업 중 점포»라 화면에서는 한 가지 뜻의 한 숫자다.

    배치로 도는 이유: S3 가 후보를 한 번에 그려서, 격자마다 조회하면 N+1 이다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}

    wanted = list({cell for gid in ids for cell in neighbors(gid, 1)})
    counts = {}
    rest = REST_UPTAE.get(uptae)
    # SQLite 의 바인드 변수 상한(기본 999)에 걸리지 않게 끊어 묻는다.
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        cells = ",".join("?" * len(chunk))
        if rest is None:
            for row in con.execute(
                f"SELECT grid_id, competitor_same_uptae FROM grid_feature "
                f"WHERE grid_id IN ({cells})",
                chunk,
            ):
                counts[row["grid_id"]] = json.loads(
                    row["competitor_same_uptae"] or "{}"
                ).get(uptae, 0)
        else:
            kinds = ",".join("?" * len(rest))
            # 조회에 안 잡힌 칸은 «모름»이 아니라 0 이다 — licence_rest 는 서울
            # 휴게음식점 전수라 그 칸에 커피숍이 없다는 뜻이다. 아래에서 0 으로
            # 채우되, grid_feature 에 아예 없는 칸과는 구분해 둔다.
            present = set()
            for row in con.execute(
                f"SELECT grid_id FROM grid_feature WHERE grid_id IN ({cells})", chunk
            ):
                present.add(row["grid_id"])
            for gid in present:
                counts[gid] = 0
            for row in con.execute(
                f"SELECT grid_id, COUNT(*) n FROM licence_rest "
                f"WHERE grid_id IN ({cells}) AND uptae IN ({kinds}) AND is_closed = 0 "
                "GROUP BY grid_id",
                [*chunk, *rest],
            ):
                if row["grid_id"] in present:
                    counts[row["grid_id"]] = row["n"]

    return {
        gid: {
            "here": counts.get(gid),
            "r1": sum(counts[cell] for cell in neighbors(gid, 1) if cell in counts),
        }
        for gid in ids
    }




def _uptae_sales_batch(con, grid_ids, uptae):
    """이 상권에 이 업종 점포가 몇 곳이고, 매출이 공표됐는가.

    매출 결측은 우리가 흘린 것이 아니라 원천이 안 준 것이다. 카드 기반 추정이라
    점포가 한두 곳이면 개별 사업자 매출이 드러나 공표하지 않는다(1곳 9.7% ·
    2곳 26.2% · 20곳 이상 99.2%). 그래서 결측 자체가 관측이고, 서울 평균으로
    메우지 않는다 — 결측이 점포 적은 상권에 몰려 있어 한산한 골목에 번화가 값이
    붙는다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}
    induty = UPTAE_INDUTY.get(uptae)
    if induty is None:
        # 그 업태는 상권분석 분류에 대응이 아예 없다 — 점포 수도 셀 수 없다.
        return {gid: {"stores": None, "published": False} for gid in ids}

    out = {}
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        holes = ",".join("?" * len(chunk))
        for row in con.execute(
            f"SELECT f.grid_id, f.trdar_cd, "
            f"       (SELECT MAX(t.stor_co) FROM trdar_store t "
            f"         WHERE t.trdar_cd = f.trdar_cd AND t.induty_cd = ?) stores, "
            f"       EXISTS (SELECT 1 FROM trdar_sales s JOIN trdar_store t2 "
            f"          ON t2.trdar_cd = s.trdar_cd AND t2.induty_cd = s.induty_cd "
            f"         AND t2.quarter = s.quarter "
            f"        WHERE s.trdar_cd = f.trdar_cd AND s.induty_cd = ? "
            f"          AND t2.stor_co > 0) published "
            f"FROM grid_feature f WHERE f.grid_id IN ({holes})",
            [induty, induty, *chunk],
        ):
            # 상권 안에서 행이 없으면 0 이다. trdar_store 는 stor_co=0 인 행도
            # 1,001개 담고 있으므로 «행 없음» 과 «0곳» 이 원천에서 같은 뜻이다.
            # 상권 밖(trdar_cd NULL, 격자의 49.5%)은 다르다 — 셀 대상이 아예
            # 없으므로 0 이 아니라 null 이다. 여기에 0 을 넣으면 «이 상권에 그
            # 업종 0곳» 이라는 없는 사실이 만들어진다 (CLAUDE.md 규칙 1).
            out[row["grid_id"]] = {
                "stores": (None if row["trdar_cd"] is None
                           else (row["stores"] if row["stores"] is not None else 0)),
                "published": bool(row["published"]),
            }
    return {gid: out.get(gid, {"stores": None, "published": False}) for gid in ids}


def _rest_food_batch(con, grid_ids):
    """휴게음식점 중 «음식점»에 해당하는 것의 칸별 집계 — 영업 중 / 개업 누계 /
    폐업 누계, 그리고 3x3 링의 영업 중.

    `grid_feature.food_store_cnt` 계열은 일반음식점만 센다. 그 컬럼은 그대로
    둔다 — `pipeline.consistency` 의 cellsum 이 원천 licence 와 대조하는
    값이라 여기서 바꾸면 교차검증이 무의미해진다. 대신 API 가 응답을 만들 때
    더한다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}

    wanted = list({cell for gid in ids for cell in neighbors(gid, 1)})
    stats = {}
    kinds = ",".join("?" * len(REST_EATERY))
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        cells = ",".join("?" * len(chunk))
        for row in con.execute(
            f"SELECT grid_id, "
            f"       SUM(1 - is_closed) alive, "
            f"       COUNT(*) opened, "
            f"       SUM(is_closed) closed "
            f"FROM licence_rest "
            f"WHERE grid_id IN ({cells}) AND uptae IN ({kinds}) "
            "GROUP BY grid_id",
            [*chunk, *REST_EATERY],
        ):
            stats[row["grid_id"]] = (
                row["alive"] or 0,
                row["opened"] or 0,
                row["closed"] or 0,
            )

    def at(gid, index):
        return stats[gid][index] if gid in stats else 0

    return {
        gid: {
            "alive": at(gid, 0),
            "opened": at(gid, 1),
            "closed": at(gid, 2),
            "alive_r1": sum(at(cell, 0) for cell in neighbors(gid, 1)),
        }
        for gid in ids
    }


# 서빙하는 두 클래스. 표기 문턱을 통과한 것이고, 못 넘은 셋(alone·couple·friend)
# 은 여기 없어서 나가지 않는다.
PARTY_SERVED = ("family", "work")
PARTY_LABEL = {"family": "가족", "work": "회식·모임"}
PARTY_SOURCE = "네이버 블로그 글 (방문객 작성) · 2026-07 수집"

# §J-1 파일럿이 잰 값. 코퍼스가 단일 라벨러가 아니게 되면서(§J-1 재판정) 이 값은
# 더 이상 전체를 설명하지 못한다 — 그래서 응답에 싣지 않고 None 을 내보낸다.
# 되살리려면 전량 재라벨 + 판정자 2인 검정을 다시 받아야 한다. 문턱 판단의 근거로
# 남겨 두는 것이지 지금 주장할 수 있는 정확도가 아니다.
PARTY_PILOT_PRECISION = {"family": 0.633, "work": 0.700}
PARTY_CLAIM = (
    "방문객이 쓴 글에서 «가족» «회식·모임» 표현이 확인된 것만 센 참고 정보입니다. "
    "정확도는 재검정 전이라 함께 싣지 않습니다. "
    "상권 단위라 같은 상권 안 자리는 같은 값이며, 등급·추천 순위에는 쓰이지 않습니다."
)


def _party_batch(con, grid_ids):
    """격자별 방문객 동반자 구성 — 그 격자가 속한 상권의 집계.

    표기 문턱을 통과한 두 클래스만 서빙한다. 떨어진 셋은 수집돼 있어도 안 나간다.

    `available=False` 는 배치 미실행, 빈 `items` 는 글이 모자라 판단 불가다.
    0 으로 내려보내면 «가족 손님이 없는 자리»라는 다른 주장이 된다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}
    empty = {"available": False, "items": [], "posts_scanned": 0,
             "labelled": 0, "unit": "상권", "source": None, "claim": None}
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'trdar_party'"
    ).fetchone():
        return {gid: dict(empty) for gid in ids}

    placeholders = ",".join("?" * len(ids))
    rows = con.execute(
        f"SELECT f.grid_id, p.party, p.n, p.posts_scanned "
        f"FROM grid_feature f JOIN trdar_party p ON p.trdar_cd = f.trdar_cd "
        f"WHERE f.grid_id IN ({placeholders})",
        ids,
    ).fetchall()

    per = {}
    for r in rows:
        per.setdefault(r["grid_id"], {})[r["party"]] = (r["n"], r["posts_scanned"])

    out = {}
    for gid in ids:
        got = per.get(gid)
        if not got:
            out[gid] = {**empty, "available": True}
            continue
        # 기각된 클래스는 합계를 내기 «전에» 뺀다. 분모에 남겨 두면 화면에 안
        # 나오면서 나오는 값의 비율을 정하게 된다.
        served = {p: v for p, v in got.items() if p in PARTY_SERVED}
        if not served:
            out[gid] = {**empty, "available": True}
            continue
        total = sum(n for n, _ in served.values())
        scanned = max(s for _, s in served.values())
        items = [
            {"party": party, "label": PARTY_LABEL[party], "posts": n,
             "share": (n / total) if total else None,
             "precision": None}
            for party, (n, _) in sorted(served.items(), key=lambda kv: -kv[1][0])
        ]
        out[gid] = {"available": True, "items": items, "posts_scanned": scanned,
                    "labelled": total, "unit": "상권",
                    "source": PARTY_SOURCE, "claim": PARTY_CLAIM}
    return out


def _sales_mix_batch(con, grid_ids):
    """이 격자가 속한 상권의 업종별 결제 구성. 카드 결제 실측이지 추정이 아니다.

    `concept_mix` 와 짝이다 — 저쪽은 상호명으로 «어떤 가게가 있나»를 세고,
    이쪽은 «어디에 돈이 도나»를 센다. 둘은 실제로 다르다: 상권 1,185곳에서
    커피는 가게 27.8% / 결제 24.7% 인데 한식은 가게 31.8% / 결제 55.1% 다.
    가게 수로 업종 수요를 짐작하면 이만큼 틀린다.

    `available=False` 는 낼 수 없는 상태다 — 상권 밖(격자의 49.5%)이거나 표가
    아직 없다. 빈 `items` 는 상권 안인데 공표된 업종이 하나도 없는 경우다.
    분기는 원천에 있는 가장 최근 것 하나로 통일한다 — 상권마다 다른 분기를
    섞으면 구성비가 시점이 다른 값들의 합이 된다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}
    blank = {"available": False, "items": [], "quarter": None,
             "total_amount": None, "unit": "상권"}
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'trdar_sales'"
    ).fetchone():
        return {gid: dict(blank) for gid in ids}
    quarter = con.execute("SELECT MAX(quarter) FROM trdar_sales").fetchone()[0]
    if quarter is None:
        return {gid: dict(blank) for gid in ids}

    holes = ",".join("?" * len(ids))
    rows = con.execute(
        f"SELECT f.grid_id, s.induty_cd, s.sales_amt, s.sales_cnt "
        f"FROM grid_feature f "
        f"JOIN trdar_sales s ON s.trdar_cd = f.trdar_cd AND s.quarter = ? "
        f"WHERE f.grid_id IN ({holes}) AND s.sales_amt > 0",
        [quarter, *ids],
    ).fetchall()
    # 상권 안이라도 요식업 행이 하나도 없을 수 있다. 상권 소속 자체는 따로
    # 물어야 «상권 밖» 과 «상권 안인데 공표 없음» 이 구분된다.
    inside = {
        r["grid_id"]
        for r in con.execute(
            f"SELECT grid_id FROM grid_feature "
            f"WHERE grid_id IN ({holes}) AND trdar_cd IS NOT NULL", ids)
    }
    per = {}
    for r in rows:
        label = FOOD_INDUTY.get(r["induty_cd"])
        if label is None:
            continue                      # 요식업 밖 업종은 이 카드의 대상이 아니다
        per.setdefault(r["grid_id"], []).append(
            {"induty": label, "amount": r["sales_amt"], "count": r["sales_cnt"]})

    out = {}
    for gid in ids:
        if gid not in inside:
            out[gid] = dict(blank)
            continue
        items = sorted(per.get(gid, []), key=lambda x: -x["amount"])
        total = sum(x["amount"] for x in items)
        for x in items:
            x["share"] = (x["amount"] / total) if total else None
        out[gid] = {"available": True, "items": items, "quarter": quarter,
                    "total_amount": total or None, "unit": "상권"}
    return out


def _concept_mix_batch(con, grid_ids):
    """격자별 주변 3x3 링의 상호명 콘셉트 구성. 추론이 아니라 집계다
    (`model/concept_mix.py`).

    S3 는 후보 20여 개를 한 번에 그리므로 격자마다 조회하면 N+1 이 된다.
    한 번의 IN 조회로 모아서 돌려준다.

    배치가 아직 안 돌았으면 `available=False` 로 알린다. 빈 구성과 미실행은
    다른 상태이므로 빈 배열로 뭉개지 않는다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}

    # 테이블 유무를 직접 묻는다. 조회를 try 로 감싸면 SQL 오류·DB 손상까지
    # "배치 미실행" 으로 위장되고, readonly_connection 이 503 으로 올릴 실패가
    # 200 으로 내려간다.
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'grid_concept'"
    ).fetchone():
        return {
            gid: {"available": False, "items": [], "shops": 0,
                  "source": None, "claim": None}
            for gid in ids
        }

    placeholders = ",".join("?" * len(ids))
    rows = con.execute(
        f"SELECT grid_id, concept, n FROM grid_concept "
        f"WHERE grid_id IN ({placeholders}) "
        "ORDER BY grid_id, n DESC, concept",
        ids,
    ).fetchall()

    meta = dict(
        con.execute(
            "SELECT k, v FROM score_meta WHERE k LIKE 'concept_mix\\_%' ESCAPE '\\'"
        ).fetchall()
    )
    by_grid = {}
    for row in rows:
        by_grid.setdefault(row["grid_id"], []).append(
            {"concept": row["concept"], "shops": row["n"]}
        )
    return {
        gid: {
            "available": True,
            "items": by_grid.get(gid, []),
            "shops": sum(item["shops"] for item in by_grid.get(gid, [])),
            "source": meta.get("concept_mix_source"),
            "claim": meta.get("concept_mix_claim"),
        }
        for gid in ids
    }
