"""FTC franchise startup-cost ingest → service/data/franchise_costs.json.

Feeds the runway upfront helper: a per-uptae «부동산 제외 창업비용» reference
(가맹비 + 교육비 + 기타(인테리어·설비 등)) surfaced through /api/meta as a
labeled hint. 가맹보증금은 합계에서 뺀다 — 사용자가 보증금을 따로 입력하므로
넣으면 이중계상이고, 임대보증금·권리금은 애초에 FTC 통계 범위 밖이다. 그래서
모든 라벨이 «보증금·권리금 제외»를 함께 말해야 한다.

Endpoint verified LIVE 2026-08-03 (new data.go.kr account key):
  https://apis.data.go.kr/1130000/FftcSclasIndutyFntnStatsService/getSclaIndutyFntnOutStats
  ?serviceKey=…&yr=2024&resultType=json  → 외식 중분류 15행, resultCode 00.

⚠️ Source data traps, all measured (do NOT "fix" these to look sensible):
  1. Field names are MISLABELED at the source. Proof: the sum identity
     smtnAmt == frcsCnt + avrgFrcsAmt + avrgFntnAmt + avrgJngEtcAmt holds on
     every row (±1 rounding). Actual meanings:
       jnghdqrtrsCnt = 가맹본부 수 (the only true count; not in the sum)
       frcsCnt       = 평균 가맹보증금액   ← an AMOUNT, not a store count
       avrgFrcsAmt   = 평균 가맹비(가입비)
       avrgFntnAmt   = 평균 가맹교육금액
       avrgJngEtcAmt = 평균 가맹기타금액 (인테리어·설비·초도물품 등)
       smtnAmt       = 창업비용 합계
     validate_rows() enforces this identity — if it ever breaks, the fields
     changed meaning and the ingest must stop, not guess.
  2. crrncyUnitCdNm says "(단위 :천원)" but the actual unit is 만원
     (일식 smtnAmt 11,016 → 1.10억: plausible; as 천원 it would be 1,100만
     for a full franchise fit-out: impossible). A range guard pins this.
  3. 까페 must map to the "커피" row by EXACT name match — substring matching
     hits "음료 (커피 외)" (= beverages EXCLUDING coffee) first.

Usage:
  python -m scripts.franchise_costs --selftest        # offline: mapping + guards
  python -m scripts.franchise_costs --fetch [--year 2024]

--fetch needs DATA_GO_KR_FTC_KEY (decoded form) in .env; falls back to
DATA_GO_KR_SERVICE_KEY. Approval is per-API (활용신청) and per-account.
"""

import argparse
import datetime
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ENDPOINT = (
    "https://apis.data.go.kr/1130000/"
    "FftcSclasIndutyFntnStatsService/getSclaIndutyFntnOutStats"
)

REQUIRED_FIELDS = (
    "indutyMlsfcNm", "jnghdqrtrsCnt", "frcsCnt",
    "avrgFrcsAmt", "avrgFntnAmt", "avrgJngEtcAmt", "smtnAmt",
)

# 헬퍼 합에 들어가는 금액 필드 (frcsCnt=가맹보증금은 제외).
HELPER_FIELDS = ("avrgFrcsAmt", "avrgFntnAmt", "avrgJngEtcAmt")

# KB 12업태 → FTC 외식 중분류 이름. (candidates, proxy). Matching is
# exact-first (after strip) — substring only as fallback for renames.
# PROXY = nearest available class; the screen label appends a marker.
UPTAE_MAP = {
    "한식": (("한식",), False),
    "까페": (("커피",), False),
    "분식": (("분식",), False),
    "통닭(치킨)": (("치킨",), False),
    "호프/통닭": (("주점",), False),
    "정종/대포집/소주방": (("주점",), True),
    "일식": (("일식",), False),
    "중국식": (("중식",), False),
    "경양식": (("서양식",), False),
    "외국음식전문점(인도,태국등)": (("기타 외국식", "외국식"), False),
    "식육(숯불구이)": (("한식",), True),
    "기타": (("기타 외식",), False),
}

RAW_OUT = ROOT / "pipeline" / "cache" / "franchise_costs_raw.json"
DATA_OUT = ROOT / "service" / "data" / "franchise_costs.json"

# 만원 단위 sanity band for the 합계 최대값. 천원이면 ×10, 원이면 ×10,000 으로
# 밴드를 벗어나므로 단위 회귀를 잡는다.
SUM_PEAK_MIN, SUM_PEAK_MAX = 1_000, 100_000


def validate_rows(rows):
    """Field presence + the mislabel sum identity + the 만원 range guard."""
    if len(rows) < 10:
        raise SystemExit(f"[shape] 외식 중분류가 {len(rows)}행뿐 — 원문 확인")
    for row in rows:
        missing = [f for f in REQUIRED_FIELDS if f not in row]
        if missing:
            raise SystemExit(
                f"[shape] 필드 소실 {missing} — actual keys: {sorted(row)}"
            )
        total = row["frcsCnt"] + sum(row[f] for f in HELPER_FIELDS)
        if abs(total - row["smtnAmt"]) > 1:
            raise SystemExit(
                "[identity] smtnAmt != 보증금+가맹비+교육비+기타 "
                f"({row['indutyMlsfcNm']}: {total} vs {row['smtnAmt']}) — "
                "필드 의미가 바뀌었다. 원문을 다시 검증할 것."
            )
    peak = max(row["smtnAmt"] for row in rows)
    if not SUM_PEAK_MIN <= peak < SUM_PEAK_MAX:
        raise SystemExit(
            f"[unit] 합계 최대 {peak} — 만원 밴드({SUM_PEAK_MIN}~{SUM_PEAK_MAX}) "
            "밖이다. 단위가 바뀌었는지 원문 확인."
        )


def map_rows(rows):
    """rows(list of raw dicts) → {uptae: {value, sourceIndustry, proxy}}."""
    by_name = {row["indutyMlsfcNm"].strip(): row for row in rows}
    out, missing = {}, []
    for uptae, (candidates, proxy) in UPTAE_MAP.items():
        # exact first — «커피» 를 부분일치로 찾으면 «음료 (커피 외)» 에 걸린다.
        hit = next((c for c in candidates if c in by_name), None)
        if hit is None:
            hit = next(
                (name for name in by_name for c in candidates if c in name),
                None,
            )
        if hit is None:
            missing.append((uptae, candidates))
            continue
        row = by_name[hit]
        out[uptae] = {
            "value": round(sum(row[f] for f in HELPER_FIELDS), 1),
            "sourceIndustry": hit,
            "proxy": proxy,
        }
    return out, missing


def fetch_rows(year, service_key):
    url = (
        f"{ENDPOINT}?serviceKey={urllib.parse.quote(service_key, safe='')}"
        f"&yr={year}&resultType=json&numOfRows=999&pageNo=1"
    )
    with urllib.request.urlopen(url, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(body, encoding="utf-8")
    payload = json.loads(body)
    if payload.get("resultCode") != "00":
        raise SystemExit(
            f"[api] resultCode {payload.get('resultCode')} "
            f"({payload.get('resultMsg')}) — 활용신청/키 확인. 원문: {RAW_OUT}"
        )
    return payload["items"]


def write_out(year, helper):
    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(
        json.dumps(
            {
                "source": "공정거래위원회 가맹정보 업종별 창업비용 (data.go.kr 15110293)",
                "endpoint": ENDPOINT,
                "year": year,
                "fetched": datetime.date.today().isoformat(),
                "unit": "만원",
                "scope": "가맹비+교육비+기타(인테리어 등) — 가맹보증금·임대보증금·권리금 제외",
                "helpers": helper,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[out] {len(helper)}/12 uptae → {DATA_OUT}")


def fetch(year):
    from pipeline.config import load_env

    env = load_env()
    key = env.get("DATA_GO_KR_FTC_KEY") or env.get("DATA_GO_KR_SERVICE_KEY")
    if not key:
        raise SystemExit("DATA_GO_KR_FTC_KEY 없음 — .env 확인")
    rows = fetch_rows(year, key)
    validate_rows(rows)
    helper, missing = map_rows(rows)
    if missing:
        raise SystemExit(f"[map] 미연결 업태 {missing} — 중분류 이름 변경 여부 확인")
    write_out(year, helper)
    for uptae, h in sorted(helper.items(), key=lambda kv: -kv[1]["value"]):
        mark = " (proxy)" if h["proxy"] else ""
        print(f"  {uptae:<22} {h['value']:>8,.0f}만원  ← {h['sourceIndustry']}{mark}")


# ── selftest (offline) ──────────────────────────────────────────────────────

# 2024 실측 6행 발췌 — 실제 응답 그대로(필드명 오배치 포함). «음료 (커피 외)»
# 가 커피 함정의 실물이라 반드시 픽스처에 남긴다.
SAMPLE_2024 = [
    {"yr": "2024", "indutyMlsfcNm": "음료 (커피 외)", "jnghdqrtrsCnt": 24,
     "frcsCnt": 283, "avrgFrcsAmt": 156, "avrgFntnAmt": 140,
     "avrgJngEtcAmt": 3058, "smtnAmt": 3638},
    {"yr": "2024", "indutyMlsfcNm": "커피", "jnghdqrtrsCnt": 35,
     "frcsCnt": 204, "avrgFrcsAmt": 109, "avrgFntnAmt": 86,
     "avrgJngEtcAmt": 2544, "smtnAmt": 2943},
    {"yr": "2024", "indutyMlsfcNm": "한식", "jnghdqrtrsCnt": 12,
     "frcsCnt": 642, "avrgFrcsAmt": 337, "avrgFntnAmt": 241,
     "avrgJngEtcAmt": 6531, "smtnAmt": 7750},
    {"yr": "2024", "indutyMlsfcNm": "주점", "jnghdqrtrsCnt": 19,
     "frcsCnt": 416, "avrgFrcsAmt": 222, "avrgFntnAmt": 123,
     "avrgJngEtcAmt": 4603, "smtnAmt": 5365},
    {"yr": "2024", "indutyMlsfcNm": "일식", "jnghdqrtrsCnt": 9,
     "frcsCnt": 962, "avrgFrcsAmt": 486, "avrgFntnAmt": 333,
     "avrgJngEtcAmt": 9234, "smtnAmt": 11016},
    {"yr": "2024", "indutyMlsfcNm": "아이스크림/빙수 ", "jnghdqrtrsCnt": 43,
     "frcsCnt": 180, "avrgFrcsAmt": 94, "avrgFntnAmt": 105,
     "avrgJngEtcAmt": 1765, "smtnAmt": 2144},
]


def selftest():
    import sqlite3

    con = sqlite3.connect(ROOT / "kb.db")
    served = {r[0] for r in con.execute("SELECT DISTINCT uptae FROM grid_score")}
    assert served == set(UPTAE_MAP), (
        f"map drift — only in DB: {served - set(UPTAE_MAP)}, "
        f"only in map: {set(UPTAE_MAP) - served}"
    )

    # identity guard: 실측 행은 전부 통과해야 하고, 의미가 바뀐 행은 잡혀야 한다.
    rows = [dict(r) for r in SAMPLE_2024] * 2  # >=10행 요건 충족
    validate_rows(rows)
    corrupted = [dict(r) for r in rows]
    corrupted[0]["frcsCnt"] = 9_999  # count 로 «정상화»된 세상
    try:
        validate_rows(corrupted)
        raise AssertionError("identity guard did not fire")
    except SystemExit:
        pass

    # 커피 함정: 까페는 정확일치로 «커피» 에 붙어야 한다.
    helper, _missing = map_rows(rows)
    assert helper["까페"]["sourceIndustry"] == "커피", helper["까페"]
    assert helper["까페"]["value"] == 109 + 86 + 2544  # 보증금(frcsCnt) 제외
    assert helper["정종/대포집/소주방"]["proxy"] is True
    # 이름 끝 공백이 있어도 strip 으로 붙는다 (아이스크림/빙수 실측).
    assert "아이스크림/빙수" in {r["indutyMlsfcNm"].strip() for r in rows}
    print("selftest PASS — identity guard, 커피 exact-match, deposit excluded")


if __name__ == "__main__":
    # Windows cp949 console cannot print the em dashes in our messages.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--year", type=int, default=2024)
    args = ap.parse_args()
    if args.selftest:
        selftest()
    elif args.fetch:
        fetch(args.year)
    else:
        ap.print_help()
