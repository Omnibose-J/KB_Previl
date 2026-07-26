"""Look up the feature row for a coordinate - the interface the recommender uses."""
import argparse
import json

from .db import init
from .grid import to_grid_id


def at(con, lon, lat, ring=0):
    gid = to_grid_id(lon, lat)
    r = con.execute("SELECT * FROM grid_feature WHERE grid_id=?", (gid,)).fetchone()
    return gid, (dict(r) if r else None)


def render(gid, f):
    if not f:
        print(f"grid_id={gid}: 데이터 없음 (음식점 이력이 한 건도 없는 격자)")
        return
    print(f"grid_id      : {gid}  ({f['center_lat']:.5f}, {f['center_lon']:.5f})")
    print(f"신뢰도       : {f['confidence']}"
          + ("  (상권 내 — 매출·유동인구 포함)" if f['confidence'] == 'full'
             else "  (상권 밖 — 매출·유동인구 없음)"))
    print(f"행정동/상권  : {f['adstrd_cd']} / {f['trdar_cd'] or '—'}")
    print()
    print(f"[경쟁] 격자 내 영업 음식점 {f['food_store_cnt']}개, 3x3 이웃 포함 {f['food_store_cnt_r1']}개")
    try:
        up = json.loads(f["competitor_same_uptae"] or "{}")
        top = sorted(up.items(), key=lambda x: -x[1])[:5]
        if top:
            print("       업태 구성: " + ", ".join(f"{k} {v}" for k, v in top))
    except Exception:
        pass
    if f["franchise_cnt"] is not None:
        print(f"       상권 내 프랜차이즈 점포수 {f['franchise_cnt']:.0f}")
    print()
    print(f"[생존] 누적 개업 {f['hist_open_cnt']} / 폐업 {f['hist_close_cnt']}")
    if f["survive_3y_local"] is not None:
        print(f"       3년 생존율 {f['survive_3y_local']}%  (표본 n={f['survive_3y_n']}, 3x3 이웃)")
    else:
        print(f"       3년 생존율 — 표본 부족 (n={f['survive_3y_n']})")
    print()
    print(f"[수요] 주간 생활인구 {f['lvpop_day']:.0f}" if f["lvpop_day"] else "[수요] 생활인구 —", end="")
    print(f" / 야간 {f['lvpop_night']:.0f}" if f["lvpop_night"] else "")
    print()
    if f["sales_amt"] is not None:
        print(f"[매출] 상권 분기 추정매출 {f['sales_amt']/1e8:.1f}억  건수 {f['sales_cnt']:,.0f}")
        print(f"[유동] 상권 유동인구 {f['flpop']:,.0f}" if f["flpop"] else "")
    else:
        print("[매출] 없음 — 이 격자는 서울시 상권 영역 밖입니다 (0이 아니라 미관측)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--lat", type=float, required=True)
    a = ap.parse_args()
    con = init()
    render(*at(con, a.lon, a.lat))
