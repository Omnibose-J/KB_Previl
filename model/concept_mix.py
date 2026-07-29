"""상호명 콘셉트 구성 — 격자 3x3 링 집계.

인허가 상호명에서 음식 콘셉트를 읽어 격자 주변(3x3 링)의 점포 구성을 만든다.
`grid_score` 나 추천 순위에 들어가지 않는다 — 화면에 내는 관측 집계다.

**추론이 아니라 집계다.** "상호명에 '국밥' 이 든 영업중 점포 3곳" 은 정밀도
게이트가 필요한 판정이 아니라 셀 수 있는 사실이다. 이 분류 체계가 관청 등록
업태와 실제로 정합한다는 근거는 docs/unstructured-plan.md §I-24·§I-26 에 있다
(추출 콘셉트 vs 업태 일치가 천장의 98.8%).

키워드가 둘 이상 걸리는 상호명은 버린다 — `본가감자탕치킨` 이 무엇인지 이 방법은
답할 수 없고, 임의로 하나를 고르면 조용히 틀린다.

    python -m model.concept_mix

`KB_DB` 로 대상 DB를 바꿀 수 있다. 이 모듈은 `grid_concept` 만 만들고 다른 테이블은
읽기만 한다.
"""
import sqlite3
import sys
from collections import Counter, defaultdict

from pipeline.config import DB_PATH, REST_EATERY_UPTAE
from pipeline.grid import neighbors

sys.stdout.reconfigure(encoding="utf-8")

RING = 1                       # competition.shops_neighbor 와 같은 이웃 규약

# 상호명 키워드 -> 콘셉트. docs/unstructured-plan.md §I-24 에 등록된 사전이다.
KW = {
    "국밥": "국밥", "설렁탕": "탕반", "곰탕": "탕반", "해장국": "탕반", "감자탕": "탕반",
    "순대": "순대", "갈비": "구이", "삼겹": "구이", "숯불": "구이", "고깃": "구이",
    "곱창": "구이", "막창": "구이", "칼국수": "면", "국수": "면", "냉면": "면",
    "막국수": "면", "우동": "면", "라멘": "면", "라면": "면", "김밥": "분식",
    "떡볶이": "분식", "만두": "분식", "돈까스": "돈까스", "돈가스": "돈까스",
    "초밥": "스시", "스시": "스시", "회": "회", "횟집": "회", "조개": "해산물",
    "장어": "해산물", "해물": "해산물", "치킨": "치킨", "통닭": "치킨", "피자": "피자",
    "파스타": "양식", "스테이크": "양식", "족발": "족발", "보쌈": "족발",
    "찜닭": "찜", "아구": "찜", "커피": "카페", "카페": "카페", "베이커리": "베이커리",
    "제과": "베이커리", "디저트": "카페", "포차": "주점", "호프": "주점", "맥주": "주점",
    "와인": "주점", "이자카야": "주점", "술집": "주점", "중화": "중식", "짜장": "중식",
    "짬뽕": "중식", "마라": "중식", "양꼬치": "중식", "쌀국수": "베트남",
    "타코": "멕시코", "카레": "카레", "부대찌개": "찌개", "김치찌개": "찌개", "두부": "두부",
}


def concept_of(name):
    """상호명에서 콘셉트 하나를 읽는다. 모호하면 None."""
    found = {v for k, v in KW.items() if k in name}
    return found.pop() if len(found) == 1 else None


def build(con):
    cells = defaultdict(Counter)
    n_named = n_open = 0

    # 일반음식점 + 휴게음식점(음식점류). 전에는 일반음식점만 읽어서 카페·
    # 베이커리가 통째로 안 잡혔다 — 사전에 «커피»·«카페»·«베이커리» 가 있는데도
    # 걸릴 상호가 없었던 것이다. 서울 영업 중 음식업의 16.9% 가 그쪽에 있다.
    ph = ",".join("?" * len(REST_EATERY_UPTAE))
    sources = [
        ("SELECT bplcnm, grid_id FROM licence "
         "WHERE bplcnm IS NOT NULL AND grid_id IS NOT NULL AND is_closed = 0", ()),
        (f"SELECT bplcnm, grid_id FROM licence_rest "
         f"WHERE bplcnm IS NOT NULL AND grid_id IS NOT NULL AND is_closed = 0 "
         f"AND uptae IN ({ph})", REST_EATERY_UPTAE),
    ]
    for sql, args in sources:
        for name, gid in con.execute(sql, args):
            n_open += 1
            c = concept_of(name)
            if c:
                cells[gid][c] += 1
                n_named += 1
    print(f"영업중 점포 {n_open:,} · 콘셉트 확정 {n_named:,} "
          f"({n_named / n_open:.1%}) · 격자 {len(cells):,}")

    grids = [r[0] for r in con.execute("SELECT grid_id FROM grid_feature")]
    rows = []
    for gid in grids:
        agg = Counter()
        for nb in neighbors(gid, RING):
            agg += cells.get(nb, Counter())
        rows += [(gid, c, n) for c, n in agg.items()]

    con.execute("CREATE TABLE IF NOT EXISTS grid_concept ("
                "grid_id TEXT NOT NULL, concept TEXT NOT NULL, n INTEGER NOT NULL,"
                "PRIMARY KEY (grid_id, concept))")
    con.execute("DELETE FROM grid_concept")
    con.executemany("INSERT INTO grid_concept VALUES(?,?,?)", rows)

    covered = len({g for g, _, _ in rows})
    con.executemany("INSERT OR REPLACE INTO score_meta VALUES(?,?)", [
        ("concept_mix_ring", str(RING)),
        ("concept_mix_source", "licence+licence_rest.bplcnm:open_only"),
        ("concept_mix_claim", "observation_only:not_predictive"),
        ("concept_mix_shops", str(n_named)),
        ("concept_mix_grids", str(covered)),
        ("concept_mix_concepts", ",".join(sorted(set(KW.values())))),
    ])
    print(f"grid_concept {len(rows):,}행 · 구성이 잡히는 격자 "
          f"{covered:,}/{len(grids):,} ({covered / len(grids):.1%})")


def main():
    con = sqlite3.connect(DB_PATH)
    try:
        build(con)
        con.commit()
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
