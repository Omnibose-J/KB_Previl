"""ABSA 실현 가능성 사전 조사 — **검정이 아니라 조사다**.

§14-C-③이 경고를 남겼다. 블로그 글의 부정 비율이 2~4%로 극단적으로 낮으니,
거기서 "입지 측면 부정"만 추리면 표본이 없을 수 있다. 본 실험(H-3)을 설계하기
전에 그 전제를 확인한다.

**이 모듈의 결과로 H-3을 설계해도 된다. 다만 H-3의 검정은 다른 표본으로 해야
한다** — 조사에서 본 데이터로 설계하고 같은 데이터로 검정하면 사후 선택이다.
그래서 조사는 마포구로 하고, H-3 착수 시 다른 구를 쓴다.

무엇을 재는가:
  1. 입지 측면을 언급하는 글의 비율        ← H-3의 분모가 될 수 있는가
  2. 그중 부정의 비율                       ← 신호가 존재하는가
  3. 협찬/체험단 글의 비율                  ← §14-C-③의 원인 가설 검증
  4. 실제 표현 예시                         ← H-3의 판정 기준 설계에 직접 쓴다

    python -m model.absa_probe --n 500
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from model.senti_gate import _headers, pick
from model.senti_dist import posts_in_window
from pipeline.config import DB_PATH, ENV_PATH

SEED = 0
MODEL = "gpt-4o-mini"

# 조사용 프롬프트. H-3 착수 시에는 이 문구를 그대로 쓰거나, 바꾼다면 바꾼
# 이유와 함께 사전 등록에 다시 적는다.
PROMPT = """다음은 한국어 음식점 관련 블로그 글의 일부다. JSON만 출력하라.

{
 "loc_mentioned": true/false,   // 가게의 '위치·입지'에 관한 언급이 있는가.
                                // 해당: 주차, 역/정류장 거리, 골목 분위기, 찾기 쉬움,
                                //       주변 상권, 유동인구, 한적함/번잡함
                                // 제외: 맛, 가격, 서비스, 메뉴, 인테리어
 "loc_sentiment": "pos"|"neg"|"neu"|null,  // 위 언급의 평가. 없으면 null
 "loc_quote": "원문에서 그 부분을 20자 이내로 인용. 없으면 빈 문자열",
 "sponsored": true/false        // 협찬·체험단·제공받았다는 표시가 있는가
}

글: """


def probe(texts, n, workers=8):
    from openai import OpenAI
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    cli = OpenAI(api_key=env["OPENAI_API_KEY"])
    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(texts), size=min(n, len(texts)), replace=False)

    def one(i):
        try:
            r = cli.chat.completions.create(
                model=MODEL, temperature=0, max_tokens=120,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": PROMPT + texts[i][:700]}])
            d = json.loads(r.choices[0].message.content)
            d["_text"] = texts[i]
            return d
        except Exception:
            return None

    out = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for d in ex.map(one, idx):
            if d:
                out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500, help="LLM 판정 글 수")
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()

    print("ABSA 실현 가능성 사전 조사 (검정 아님)")
    print("표본: 마포구 — H-3 착수 시에는 다른 구를 써야 한다\n")

    con = sqlite3.connect(DB_PATH)
    sample = pick(con)
    con.close()

    h = _headers()
    t0 = time.time()
    texts = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for posts, _tr in ex.map(lambda r: posts_in_window(h, r[1], r[2], r[3]),
                                 sample):
            if posts:
                texts += posts
    print(f"글 수집 {len(texts):,}건 · {time.time()-t0:.0f}초")

    print(f"LLM 판정 {a.n}건 (model={MODEL}) …", flush=True)
    t1 = time.time()
    res = probe(texts, a.n)
    print(f"  판정 완료 {len(res)}건 · {time.time()-t1:.0f}초\n")
    if not res:
        print("판정 실패 — SKIP")
        return 1

    n = len(res)
    loc = [d for d in res if d.get("loc_mentioned")]
    spon = sum(1 for d in res if d.get("sponsored"))
    sent = Counter(d.get("loc_sentiment") for d in loc)

    print("=" * 62)
    print(f"{'입지 언급 글':<22s} {len(loc):5d} / {n}  ({len(loc)/n:.1%})")
    print(f"{'└ 긍정':<22s} {sent.get('pos', 0):5d}"
          f"  ({sent.get('pos', 0)/max(len(loc), 1):.1%} of 입지 언급)")
    print(f"{'└ 부정':<22s} {sent.get('neg', 0):5d}"
          f"  ({sent.get('neg', 0)/max(len(loc), 1):.1%})")
    print(f"{'└ 중립':<22s} {sent.get('neu', 0):5d}")
    print(f"{'협찬/체험단 표시':<22s} {spon:5d} / {n}  ({spon/n:.1%})")
    print("=" * 62)

    neg_all = sent.get("neg", 0) / n
    print(f"\n전체 글 중 '입지 부정' 비율: {neg_all:.2%}")
    print(f"→ 격자당 이 신호를 1건 얻으려면 글이 약 {1/max(neg_all, 1e-9):.0f}건 필요")

    print("\n--- 입지 언급 예시 (부정 우선) ---")
    ws = re.compile(r"\s+")
    shown = 0
    for want in ("neg", "pos"):
        for d in loc:
            if d.get("loc_sentiment") == want and (d.get("loc_quote") or "").strip():
                body = ws.sub(" ", d["_text"])[:60]
                print(f"  [{want}] {d['loc_quote'][:40]:<42s} | {body}")
                shown += 1
                if shown >= 12:
                    break
        if shown >= 12:
            break

    print("\n--- H-3 설계에 주는 함의 ---")
    if neg_all < 0.01:
        print("  입지 부정이 전체의 1% 미만. 격자 단위 지표를 만들려면 격자당")
        print("  글이 수백 건 필요하다 → 마포구 규모로는 불가능할 수 있다.")
        print("  대안: (a) 부정만이 아니라 '입지 언급 자체'를 지표로,")
        print("        (b) 격자가 아니라 지명 단위로 올린다.")
    else:
        print("  입지 부정이 1% 이상. 격자당 글 수를 확인하면 지표 산출 가능성이")
        print("  나온다. H-3 사전 등록에 최소 표본 조건을 넣을 것.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
