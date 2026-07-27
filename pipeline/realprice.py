"""상업업무용 부동산 매매 실거래가 — 법정동 단위 가격 시계열.

왜 이것을 붙이는가: Glaeser·Kim·Luca(2018)는 "어떤 업종이 들어오는가"가
**주택가격 변화에 선행한다**를 보였다. 우리 §11-D는 같은 예측변수를 썼지만
결과변수가 개업 유입률이었고, 그건 과거 유입률이 거의 다 설명해버려서 남는
분산이 얇았다. 가격은 다른 축이다.

단위가 법정동인 것이 중요하다. API는 좌표를 주지 않고 지번도 마스킹한다
(`7*`). 그러나 격자로 내리는 것은 애초에 금지이므로(공간해상도 원칙) 손해가
아니다. `licence.addr`에서 법정동이 99.9% 추출되고 API의 `sggNm`+`umdNm`과
같은 단위라 매핑표 없이 직접 조인된다.

    python -m pipeline.realprice                 # 2014-01 ~ 2025-12 전체
    python -m pipeline.realprice --workers 8
    python -m pipeline.realprice --stats         # 적재 현황만
"""
import argparse
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import requests

from .config import ENV_PATH
from .db import init

API = ("https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/"
       "getRTMSDataSvcNrgTrade")
PER_REQ = 1000
MAX_HOURS = 4.0          # 자율 규칙: 수집이 4시간을 넘으면 중단하고 "측정 못 함"

# 서울 25개 자치구 법정동코드 앞 5자리
SEOUL_SGG = [
    "11110", "11140", "11170", "11200", "11215", "11230", "11260", "11290",
    "11305", "11320", "11350", "11380", "11410", "11440", "11470", "11500",
    "11530", "11545", "11560", "11590", "11620", "11650", "11680", "11710",
    "11740",
]

_local = threading.local()


def _key():
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    return env.get("DATA_GO_KR_SERVICE_KEY") or env["DATA_GO_KR_API_KEY"]


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        _local.s = s
    return s


def _num(x, cast=float):
    t = (x or "").strip().replace(",", "")
    if not t:
        return None
    try:
        return cast(t)
    except ValueError:
        return None


def fetch(key, sgg, ym, tries=3):
    """-> (rows, ok). ok=False 면 그 (구,월)은 적재하지 않는다 — 0건과 실패는 다르다."""
    for attempt in range(tries):
        try:
            r = _session().get(API, timeout=30, params={
                "serviceKey": key, "LAWD_CD": sgg, "DEAL_YMD": ym,
                "numOfRows": str(PER_REQ), "pageNo": "1"})
            if r.status_code != 200:
                time.sleep(1 + attempt)
                continue
            root = ET.fromstring(r.text)
            code = root.findtext(".//resultCode")
            if code not in ("000", "00"):
                time.sleep(1 + attempt)
                continue
            out = []
            for it in root.findall(".//item"):
                g = lambda t: (it.findtext(t) or "").strip()      # noqa: E731
                y, m = _num(g("dealYear"), int), _num(g("dealMonth"), int)
                if not y or not m:
                    continue
                out.append((
                    sgg, g("umdNm"), y * 12 + m, _num(g("dealDay"), int),
                    _num(g("dealAmount")), _num(g("buildingAr")),
                    _num(g("floor"), int), g("buildingUse"), g("buildingType"),
                    _num(g("buildYear"), int), g("landUse"),
                ))
            return out, True
        except (requests.RequestException, ET.ParseError):
            time.sleep(1 + attempt)
    return [], False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-ym", default="201401")
    ap.add_argument("--to-ym", default="202512")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    con = init()
    con.execute("""CREATE TABLE IF NOT EXISTS realprice (
        sgg_cd     TEXT,
        umd_nm     TEXT,
        deal_ym    INTEGER,
        deal_day   INTEGER,
        amount     REAL,          -- 만원
        area       REAL,          -- 건물면적 m2
        floor      INTEGER,
        bldg_use   TEXT,
        bldg_type  TEXT,
        build_year INTEGER,
        land_use   TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS realprice_done (
        sgg_cd TEXT, deal_ymd TEXT, n INTEGER,
        PRIMARY KEY (sgg_cd, deal_ymd)
    )""")
    con.commit()

    if a.stats:
        n, = con.execute("SELECT count(*) FROM realprice").fetchone()
        d, = con.execute("SELECT count(*) FROM realprice_done").fetchone()
        print(f"realprice {n:,}행 · 완료 (구,월) {d:,}")
        print("법정동 수:", con.execute(
            "SELECT count(DISTINCT sgg_cd||umd_nm) FROM realprice").fetchone()[0])
        print("기간:", con.execute(
            "SELECT min(deal_ym), max(deal_ym) FROM realprice").fetchone())
        for u, c in con.execute("SELECT bldg_use, count(*) FROM realprice "
                                "GROUP BY 1 ORDER BY 2 DESC LIMIT 8"):
            print(f"  {u:24s} {c:,}")
        return 0

    y0, m0 = int(a.from_ym[:4]), int(a.from_ym[4:])
    y1, m1 = int(a.to_ym[:4]), int(a.to_ym[4:])
    yms = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        yms.append(f"{y}{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1

    done = {(r[0], r[1]) for r in con.execute(
        "SELECT sgg_cd, deal_ymd FROM realprice_done")}
    jobs = [(s, d) for s in SEOUL_SGG for d in yms if (s, d) not in done]
    print(f"대상 {len(SEOUL_SGG)}구 x {len(yms)}개월 = {len(SEOUL_SGG)*len(yms):,} "
          f"· 이미 완료 {len(done):,} · 남은 요청 {len(jobs):,}")
    if not jobs:
        print("할 일 없음")
        return 0

    key = _key()
    t0 = time.time()
    state = {"n": 0, "rows": 0, "fail": 0, "stop": False}

    # 워커는 네트워크만 한다. sqlite 커넥션은 만든 스레드에 묶여 있으므로
    # 쓰기는 전부 메인 스레드에서 한다.
    def work(job):
        sgg, ymd = job
        if state["stop"]:
            return sgg, ymd, [], False
        rows, ok = fetch(key, sgg, ymd)
        return sgg, ymd, rows, ok

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for sgg, ymd, rows, ok in ex.map(work, jobs):
            if not ok:
                state["fail"] += 1
            else:
                if rows:
                    con.executemany(
                        "INSERT INTO realprice VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
                con.execute("INSERT OR REPLACE INTO realprice_done VALUES(?,?,?)",
                            (sgg, ymd, len(rows)))
                state["rows"] += len(rows)
            state["n"] += 1
            if state["n"] % 200 == 0:
                con.commit()
                el = (time.time() - t0) / 60
                print(f"  {state['n']:,}/{len(jobs):,} · {state['rows']:,}행 · "
                      f"실패 {state['fail']} · {el:.1f}분", flush=True)
            if (time.time() - t0) > MAX_HOURS * 3600:
                state["stop"] = True
    con.commit()

    el = (time.time() - t0) / 60
    print(f"\n완료 {state['n']:,}요청 · {state['rows']:,}행 · 실패 {state['fail']} "
          f"· {el:.1f}분")
    if state["stop"]:
        print("!! 4시간 상한 도달로 중단 — 남은 구간은 재실행하면 이어받는다")
    if state["fail"]:
        print(f"!! 실패한 (구,월) {state['fail']}건은 적재하지 않았다 — "
              f"0건과 구분하기 위해서다. 재실행하면 다시 시도한다")
    n, = con.execute("SELECT count(*) FROM realprice").fetchone()
    print(f"realprice 총 {n:,}행")
    return 0


if __name__ == "__main__":
    sys.exit(main())
