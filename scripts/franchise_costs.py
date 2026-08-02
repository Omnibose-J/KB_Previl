"""FTC franchise startup-cost ingest for the runway upfront helper.

Turns 공정위 가맹정보 창업비용 (data.go.kr) into a per-uptae default for the
"그 외 초기투자" input (S5) and the S4 upfront hint. DELIBERATELY excludes the
franchise deposit from the helper value — the user types 보증금·권리금
separately, so including it would double-count.

Usage:
  python -m scripts.franchise_costs --selftest      # no network — mapping + conversion
  python -m scripts.franchise_costs --fetch [--year 2024]

--fetch needs DATA_GO_KR_SERVICE_KEY *approved for this API* (활용신청 per API;
the SEMAS approval does not carry over). Portal maintenance until 2026-08-03
09:00 blocks the 신청, not necessarily the endpoint.

Exact response field names are unknown until the portal reopens, so nothing is
hardcoded: every concept is resolved against the actual payload keys and the
script aborts listing the real keys when a concept cannot be resolved
unambiguously. When real data lands, a mismatch is a one-line candidate fix.

Landing plan for the produced dict (not wired yet on purpose — no dead config):
runway_params.UPFRONT_HELPER_BY_UPTAE, surfaced through /api/meta as a labeled
hint ("공정위 YYYY 가맹 평균") — display + one-tap apply, never silently
prefilled into a calculation.
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Candidate endpoints, most useful first. 업종별(15110293) may stop at the
# 대분류 grain ("외식" one row); the 브랜드별(15110265) fallback always carries
# enough rows to aggregate a 중분류 median ourselves.
ENDPOINTS = {
    "by_industry": "https://apis.data.go.kr/1130000/FftcIndutyFrcsCstStatsService/getIndutyFrcsCstStats",
    "by_brand": "https://apis.data.go.kr/1130000/FftcBrandFrcsCstStatsService/getBrandFrcsCstStats",
}

# concept -> plausible field-name candidates. Resolution demands exactly one
# hit against the real payload; anything else aborts with the actual keys.
FIELD_CANDIDATES = {
    "industry_mid": ("indutyMlsfcNm", "indutyMclasNm", "induty_mlsfc_nm", "indutyNm"),
    "franchise_fee": ("frcsFee", "jnngFee", "frcsBcncJnngAmt", "joinAmt"),
    "education_fee": ("eduFee", "frcsBcncEduAmt", "educationAmt"),
    "deposit": ("guartAmt", "frcsBcncGuartAmt", "gtyAmt"),
    "etc_cost": ("etcAmt", "frcsBcncEtcAmt", "etcCost"),
}

# KB 12업태 -> FTC 외식 중분류 name candidates. PROXY = nearest available
# class, labeled so the screen can say so. Validated against kb.db in selftest.
UPTAE_MAP = {
    "한식": (("한식",), False),
    "까페": (("커피", "커피전문점"), False),
    "분식": (("분식", "김밥·간이음식", "김밥"), False),
    "통닭(치킨)": (("치킨",), False),
    "호프/통닭": (("주점", "생맥주·기타주점", "호프"), False),
    "정종/대포집/소주방": (("주점", "생맥주·기타주점"), True),
    "일식": (("일식",), False),
    "중국식": (("중식",), False),
    "경양식": (("서양식",), False),
    "외국음식전문점(인도,태국등)": (("외국식",), False),
    "식육(숯불구이)": (("한식",), True),
    "기타": (("기타 외식", "기타외식"), False),
}

RAW_OUT = ROOT / "pipeline" / "cache" / "franchise_costs_raw.json"


def resolve_field(row, concept):
    hits = [k for k in FIELD_CANDIDATES[concept] if k in row]
    if len(hits) != 1:
        raise SystemExit(
            f"[shape] {concept}: candidates {FIELD_CANDIDATES[concept]} matched "
            f"{hits or 'nothing'} — actual keys: {sorted(row)}"
        )
    return hits[0]


def money_divisor(all_values):
    """원 vs 천원 is a property of the FILE, not of one value — a 50만원
    education fee in 원 sits in the ambiguous band and must not abort alone.
    Decide once from the largest money value; refuse only a wholly ambiguous
    file instead of guessing."""
    peak = max(float(v) for v in all_values if v not in (None, ""))
    if peak >= 1_000_000:  # 원 — franchise fees land in the millions
        return 10_000
    if peak < 100_000:  # 천원
        return 10
    raise SystemExit(f"[unit] ambiguous money scale (peak {peak}) — inspect raw dump")


def map_rows(rows):
    """rows: [{industry_mid_name: str, fee/edu/etc in 만원}] -> per-uptae helper."""
    by_industry = {}
    for row in rows:
        by_industry.setdefault(row["industry"], []).append(
            row["franchise_fee"] + row["education_fee"] + row["etc_cost"]
        )
    medians = {
        name: sorted(vals)[len(vals) // 2] for name, vals in by_industry.items()
    }
    out, missing = {}, []
    for uptae, (candidates, proxy) in UPTAE_MAP.items():
        hit = next((c for c in candidates if c in medians), None)
        if hit is None:
            missing.append((uptae, candidates))
            continue
        out[uptae] = {
            "value": round(medians[hit], 1),
            "source_industry": hit,
            "proxy": proxy,
        }
    return out, missing


def selftest():
    import sqlite3

    con = sqlite3.connect(ROOT / "kb.db")
    served = {r[0] for r in con.execute("SELECT DISTINCT uptae FROM grid_score")}
    assert served == set(UPTAE_MAP), (
        f"map drift — only in DB: {served - set(UPTAE_MAP)}, "
        f"only in map: {set(UPTAE_MAP) - served}"
    )

    # ASSUMED-shape sample (field names are placeholders; resolution is what
    # is under test, values are round-trip fixtures in 원).
    sample = [
        {"indutyMlsfcNm": n, "frcsFee": 10_000_000, "eduFee": 2_000_000,
         "guartAmt": 5_000_000, "etcAmt": 30_000_000}
        for n in ("한식", "커피", "분식", "치킨", "주점", "일식", "중식",
                  "서양식", "외국식", "기타 외식")
    ]
    # 교육비를 일부러 모호 구간(50만원=500,000원)에 두어 파일 단위 판정을 검증.
    sample[0]["eduFee"] = 500_000
    key = {c: resolve_field(sample[0], c) for c in FIELD_CANDIDATES}
    money_concepts = ("franchise_fee", "education_fee", "deposit", "etc_cost")
    div = money_divisor(
        r[key[c]] for r in sample for c in money_concepts
    )
    assert div == 10_000, div
    rows = [
        {
            "industry": r[key["industry_mid"]],
            "franchise_fee": r[key["franchise_fee"]] / div,
            "education_fee": r[key["education_fee"]] / div,
            "etc_cost": r[key["etc_cost"]] / div,
        }
        for r in sample
    ]
    helper, missing = map_rows(rows)
    assert not missing, f"unmapped uptae: {missing}"
    assert len(helper) == 12 and helper["한식"]["value"] == 4050.0
    assert helper["식육(숯불구이)"]["proxy"] is True
    assert sample[0][key["deposit"]] / div == 500.0  # excluded from the helper sum
    print("selftest PASS — 12/12 uptae mapped, deposit excluded, 원→만원 ok")


def fetch(year):
    from pipeline.config import load_env

    service_key = load_env().get("DATA_GO_KR_SERVICE_KEY")
    if not service_key:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY 없음 — .env 확인")
    for name, base in ENDPOINTS.items():
        url = (f"{base}?serviceKey={urllib.parse.quote(service_key)}"
               f"&yr={year}&resultType=json&numOfRows=999&pageNo=1")
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
        except OSError as exc:
            print(f"[{name}] FAIL — {exc}")
            continue
        RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
        RAW_OUT.write_text(body, encoding="utf-8")
        print(f"[{name}] {len(body):,} bytes → {RAW_OUT}")
        if "SERVICE_ACCESS_DENIED" in body or "SERVICE ERROR" in body:
            print(f"[{name}] 활용신청 미승인으로 보인다 — data.go.kr 에서 신청")
            continue
        try:
            payload = json.loads(body)
        except ValueError:
            print(f"[{name}] JSON 아님(아마 XML 오류 응답) — 원문을 열어 확인")
            continue
        print(f"[{name}] top-level keys: {list(payload)[:8]}")
        return
    raise SystemExit("두 엔드포인트 모두 실패 — 내일 9시 포털 재개 후 재시도")


if __name__ == "__main__":
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
