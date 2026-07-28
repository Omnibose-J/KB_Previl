"""판정 결과를 r1 단위 산출물로 집계한다. 형태는 §I-10-③, 최소 표본은 §I-3.

§I-10-⑥ — r1은 **표현** 단위다. 검정은 지명에서 하고(창이 겹치고 대조군이 상권
단위라 CI가 좁아진다), 화면에 내보내는 값만 r1으로 만든다.

§I-10-③ — 집계하면 죽는 것이 있다.
  가격·목적    → **비율/중앙값** (r1 집계)
  경쟁자 약점  → **목록** (점포 단위 유지). "이 동네 대기 불만 43%" 보다
                "반경 내 대기 불만이 있는 가게: A·B·C" 가 쓸모 있다.

이 단계는 LLM을 부르지 않는다. `text_profile` 테이블만 만들고 **제품에 노출하지
않는다** — 노출은 각 검정(§I-9·§I-11)의 통과 여부가 정한다.

    python -m model.profile_build
    python -m model.profile_build --coverage   # 정형 결손을 얼마나 덮는지만
"""
import argparse
import sqlite3
import sys
from collections import defaultdict

import numpy as np

from model.gripe_run import CATS, CONSTRAINT
from pipeline.config import DB_PATH

MIN_N = 10       # §I-3 규칙 3 — 미달이면 그 항목을 만들지 않는다. 0으로 안 채운다
MAX_SHOPS = 8    # 목록에 싣는 점포 수 상한 (화면용)

# §I-9는 기각됐다 (rho +0.138, CI [-0.201,+0.420], 47지명 — §17).
# 등록 문구는 "이 키를 만들지 않는다" 였다. 집계값을 테이블에 남겨 두면 누군가
# 배선해서 기각된 신호가 제품에 실린다. 원천(`price_label`)은 그대로 두고
# 집계만 하지 않는다.
EXPOSE_PRICE = False


def r1_of(gid):
    x, y = map(int, gid.split("_"))
    return [f"{x+dx}_{y+dy}" for dx in (-1, 0, 1) for dy in (-1, 0, 1)]


def shop_grid(con):
    """(place, 상호명) → 격자. 모호하면 버린다 (§15-H 조인 부풀리기 방지)."""
    g2p = dict(con.execute("SELECT grid_id, place FROM grid_place"))
    grids = defaultdict(set)
    for gid, nm in con.execute(
            "SELECT grid_id, bplcnm FROM licence "
            "WHERE grid_id IS NOT NULL AND bplcnm IS NOT NULL"):
        p = g2p.get(gid)
        if p:
            grids[(p, nm.strip())].add(gid)
    return {k: next(iter(v)) for k, v in grids.items() if len(v) == 1}


def init_db(con):
    con.execute("""CREATE TABLE IF NOT EXISTS text_profile (
        grid_id TEXT PRIMARY KEY,
        n_post INTEGER,
        price_med INTEGER, price_q1 INTEGER, price_q3 INTEGER, price_n INTEGER,
        gripe_n INTEGER, gripe_share TEXT, gripe_shops TEXT)""")
    con.commit()


def build(con):
    sg = shop_grid(con)
    print(f"격자가 하나로 정해지는 점포 {len(sg):,}곳")

    # --- 글 → 격자
    post_grid = {}
    for rid, place, mg in con.execute("SELECT rowid, place, mgtno FROM absa_post"):
        g = sg.get((place, mg))
        if g:
            post_grid[rid] = g
    print(f"격자가 붙는 글 {len(post_grid):,} / {con.execute('SELECT count(*) FROM absa_post').fetchone()[0]:,}")

    # --- 격자별 원자료
    g_posts = defaultdict(int)
    for g in post_grid.values():
        g_posts[g] += 1

    g_price = defaultdict(list)
    try:
        for rid, v in con.execute("SELECT rowid_post, per_person FROM price_label "
                                  "WHERE per_person IS NOT NULL"):
            g = post_grid.get(rid)
            if g:
                g_price[g].append(v)
    except sqlite3.OperationalError:
        print("price_label 없음 — 가격 항목 건너뜀")

    g_gripe = defaultdict(lambda: defaultdict(set))   # grid → cat → {상호명}
    g_gripe_n = defaultdict(int)
    try:
        cols = ",".join(CATS)
        for row in con.execute(f"SELECT rowid_post, mgtno, {cols} FROM gripe_label"):
            g = post_grid.get(row[0])
            if not g:
                continue
            g_gripe_n[g] += 1
            for c, v in zip(CATS, row[2:]):
                if v:
                    g_gripe[g][c].add(row[1])
    except sqlite3.OperationalError:
        print("gripe_label 없음 — 불만 항목 건너뜀")

    # --- r1 집계
    init_db(con)
    con.execute("DELETE FROM text_profile")
    all_grids = [r[0] for r in con.execute("SELECT grid_id FROM grid_feature")]
    rows = []
    for gid in all_grids:
        nb = r1_of(gid)
        n_post = sum(g_posts.get(b, 0) for b in nb)
        if n_post < MIN_N:
            continue                       # §I-3 — 미달이면 만들지 않는다

        pv = [v for b in nb for v in g_price.get(b, ())]
        if EXPOSE_PRICE and len(pv) >= MIN_N:
            a = np.array(pv)
            pmed, pq1, pq3, pn = (int(np.median(a)), int(np.percentile(a, 25)),
                                  int(np.percentile(a, 75)), len(pv))
        else:
            pmed = pq1 = pq3 = None
            pn = len(pv)       # 표본 수만 남긴다 — 왜 비었는지 추적용

        gn = sum(g_gripe_n.get(b, 0) for b in nb)
        share = shops = None
        if gn >= MIN_N:
            merged = defaultdict(set)
            for b in nb:
                for c, s in g_gripe.get(b, {}).items():
                    merged[c] |= s
            # 비율은 참고값, 목록이 본체 (§I-10-③)
            share = "|".join(f"{c}:{len(merged[c])/gn:.3f}" for c in CATS
                             if merged.get(c))
            shops = ";".join(
                f"{c}:{'|'.join(sorted(merged[c])[:MAX_SHOPS])}"
                for c in CATS if merged.get(c))
        rows.append((gid, n_post, pmed, pq1, pq3, pn, gn, share, shops))

    con.executemany("INSERT INTO text_profile VALUES(?,?,?,?,?,?,?,?,?)", rows)
    declare(con, len(rows))
    con.commit()
    print(f"text_profile {len(rows):,}격자 (r1 글 {MIN_N}건 이상)")
    return len(rows)


def declare(con, n_grid):
    """무엇이 노출 승인됐는지 `score_meta` 에 적는다.

    표를 읽는 쪽이 "이 값이 무엇을 근거로 화면에 나가는가"를 코드 밖에서 알 수
    있어야 한다. 검정을 통과한 것만 `exposed` 에 들어간다 — §I-9 는 기각이라
    가격이 빠져 있고, 그 사실도 함께 적는다(통과한 것만 적으면 기록이 아니다).
    """
    n_gripe, = con.execute(
        "SELECT count(*) FROM text_profile WHERE gripe_shops IS NOT NULL").fetchone()
    con.executemany("INSERT OR REPLACE INTO score_meta VALUES(?,?)", [
        ("text_profile_exposed", "gripe"),
        ("text_profile_grids", str(n_grid)),
        ("text_profile_gripe_grids", str(n_gripe)),
        ("text_profile_min_n", str(MIN_N)),
        # §I-11 — parking 은 창업자가 고칠 수 없는 입지 제약이다. 고칠 수 있는
        # 것과 한 목록에 두면 못 고칠 것을 고칠 것처럼 읽힌다. 화면에서 분리한다.
        ("text_profile_gripe_fixable",
         "|".join(c for c in CATS if c not in CONSTRAINT)),
        ("text_profile_gripe_constraint", "|".join(CONSTRAINT)),
        ("text_profile_source", "blog:naver · 2018-01~2018-12 · 지명 150"),
        # 예측이 아니라 관측 사실이다 (§I-3 규칙 2). 생존·등급과 연결짓지 않는다.
        ("text_profile_claim", "observation_only:not_predictive"),
        ("text_profile_verdicts",
         "I-11:pass(agree=0.996) · I-13:pass(macroF1=0.4701) · I-9:reject(rho=0.138)"),
    ])


def coverage(con):
    """정형이 비어 있는 곳을 얼마나 덮는가 — §I-5 가 주장한 것의 실측."""
    try:
        prof = {r[0]: r[1:] for r in con.execute(
            "SELECT grid_id, price_med, gripe_n FROM text_profile")}
    except sqlite3.OperationalError:
        print("text_profile 없음")
        return
    tot = out = out_cov = 0
    price_out = 0
    for gid, amt, cnt in con.execute(
            "SELECT grid_id, sales_amt, sales_cnt FROM grid_feature"):
        tot += 1
        has_sales = amt is not None and cnt not in (None, 0)
        if has_sales:
            continue
        out += 1
        p = prof.get(gid)
        if p:
            out_cov += 1
            if p[0] is not None:
                price_out += 1
    print(f"\n전체 격자           {tot:,}")
    print(f"정형 객단가 없음     {out:,} ({out/tot:.1%})   ← 상권 밖, 창업자는 여기서도 가격을 정해야 한다")
    print(f"  └ 텍스트 있음     {out_cov:,} ({out_cov/max(out,1):.1%})")
    print(f"  └ 가격 추정 가능   {price_out:,} ({price_out/max(out,1):.1%})")
    n_price, = con.execute(
        "SELECT count(*) FROM text_profile WHERE price_med IS NOT NULL").fetchone()
    n_gripe, = con.execute(
        "SELECT count(*) FROM text_profile WHERE gripe_shops IS NOT NULL").fetchone()
    print(f"\ntext_profile 중 가격 {n_price:,}격자 · 불만 목록 {n_gripe:,}격자")
    fix = " · ".join(c for c in CATS if c not in CONSTRAINT)
    print(f"불만 범주 — 고칠 수 있는 것: {fix}   / 입지 제약: {' · '.join(CONSTRAINT)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect(DB_PATH)
    if not a.coverage:
        build(con)
    coverage(con)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
