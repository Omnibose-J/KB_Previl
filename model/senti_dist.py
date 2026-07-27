"""H-2 — 감성 **분포** 편향 검정.

§13(G-1)은 "글의 양"이 생존과 연관됨을 보였다. 비율 지표는 양에 불변이므로
그 편향을 피할 수 있다 — 글이 10개든 100개든 "부정 비율 30%"는 같은 의미다.
**그러나 남아 있는 글의 감성 구성 자체가 생존과 연관되면 비율도 오염된다.**
이 모듈이 그것을 검정한다.

표본은 §G-1과 동일하다. 다른 표본을 쓰면 §13과 비교가 안 된다.
임계는 docs/unstructured-plan.md §H-7에 실행 전 등록되어 있고, 감성 사전은
`model/senti_lex.py`에 커밋되어 있다(해시를 결과에 함께 싣는다).

    python -m model.senti_dist
    python -m model.senti_dist --llm 200
"""
import argparse
import re
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from model.senti_gate import API, _headers, _sess, pick, ym
from model.senti_lex import LLM_PROMPT, score
from pipeline.config import DB_PATH, ENV_PATH

SEED = 0
NBOOT = 2000
MIN_POSTS = 3        # §H-7 — 비율이 의미를 가지려면 분모가 필요하다
RATE_RULE = 0.10
LLM_MIN_AGREE = 0.60
TAG = re.compile(r"<[^>]+>")


def posts_in_window(h, dong, name, open_ym, tries=3):
    """관측 창(개업 +12~+24m)에 쓰인 글의 본문. -> (list[str], truncated)"""
    lo, hi = open_ym + 12, open_ym + 24
    for a in range(tries):
        try:
            r = _sess(h).get(API, timeout=20, params={
                "query": f"{dong} {name}", "display": 100, "sort": "sim"})
            if r.status_code != 200:
                time.sleep(1 + a)
                continue
            d = r.json()
            out = []
            for it in d.get("items", []):
                pd = (it.get("postdate") or "").strip()
                if len(pd) != 8:
                    continue
                t = ym(int(pd[:4]), int(pd[4:6]))
                if lo <= t < hi:
                    txt = TAG.sub("", (it.get("title") or "") + " "
                                  + (it.get("description") or ""))
                    out.append(txt.strip())
            return out, 1 if int(d.get("total") or 0) > 100 else 0
        except (requests.RequestException, ValueError):
            time.sleep(1 + a)
    return None, None


def lex_hash():
    try:
        return subprocess.run(["git", "log", "-1", "--format=%h", "--",
                               "model/senti_lex.py"],
                              capture_output=True, text=True, timeout=10
                              ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def llm_check(texts, n, model="gpt-4o-mini"):
    """규칙 판정과 LLM 판정의 일치율. -> (agree, n_used, model)"""
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
    lab = {"pos": "positive", "neg": "negative", "neu": "neutral"}

    def one(i):
        t = texts[i]
        try:
            r = cli.chat.completions.create(
                model=model, temperature=0, max_tokens=5,
                messages=[{"role": "user", "content": LLM_PROMPT + t[:600]}])
            got = (r.choices[0].message.content or "").strip().lower()
            return lab[score(t)[2]], got
        except Exception:
            return None, None

    agree = tot = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for mine, got in ex.map(one, idx):
            if mine is None or not got:
                continue
            tot += 1
            if got.startswith(mine[:3]):
                agree += 1
    return (agree / tot if tot else 0.0), tot, model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--llm", type=int, default=200)
    a = ap.parse_args()

    print(f"H-2 감성 분포 편향 검정 · 감성 사전 커밋 {lex_hash()}")
    print("표본은 §G-1과 동일 · 관측 창 = 개업 +12~+24개월\n")

    con = sqlite3.connect(DB_PATH)
    sample = pick(con)
    con.close()

    h = _headers()
    t0 = time.time()

    def work(r):
        posts, trunc = posts_in_window(h, r[1], r[2], r[3])
        return r, posts, trunc

    rows, all_txt = [], []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r, posts, trunc in ex.map(work, sample):
            if posts is None or len(posts) < MIN_POSTS:
                continue
            labs = [score(t)[2] for t in posts]
            judged = [x for x in labs if x != "neu"]
            all_txt += posts
            rows.append({
                "arm": r[4], "open": r[3], "n": len(posts),
                "n_judged": len(judged),
                "neg_ratio": (labs.count("neg") / len(judged)) if judged else None,
                "trunc": trunc,
            })
    print(f"조회 완료 · {time.time()-t0:.0f}초 · 글 3건 이상 점포 {len(rows)}"
          f" · 수집 글 {len(all_txt):,}")

    use = [r for r in rows if r["neg_ratio"] is not None]
    cl = [r for r in use if r["arm"] == "폐업"]
    al = [r for r in use if r["arm"] == "생존"]
    print(f"판정 가능(중립 아닌 글 1건 이상) 점포 — 폐업 {len(cl)} · 생존 {len(al)}")
    if len(cl) < 30 or len(al) < 30:
        print("표본 부족 — 판정 보류")
        return 1

    nc = np.array([r["neg_ratio"] for r in cl])
    na = np.array([r["neg_ratio"] for r in al])
    diff = nc.mean() - na.mean()
    rng = np.random.default_rng(SEED)
    boot = np.array([
        nc[rng.integers(0, len(nc), len(nc))].mean()
        - na[rng.integers(0, len(na), len(na))].mean() for _ in range(NBOOT)])
    lo, hi = np.percentile(boot, [2.5, 97.5])

    print(f"\n{'':6s} {'n':>5s} {'부정비율':>9s} {'판정글/점포':>12s}")
    for nm, g, v in (("폐업", cl, nc), ("생존", al, na)):
        print(f"{nm:6s} {len(g):5d} {v.mean():9.1%} "
              f"{np.mean([x['n_judged'] for x in g]):12.1f}")
    print(f"\n부정 비율 차이 (폐업 − 생존) {diff:+.1%}  "
          f"95% CI [{lo:+.1%}, {hi:+.1%}]")

    agree, n_used, mdl = (None, 0, None)
    if a.llm:
        print(f"\nLLM 검증 {a.llm}건 …", flush=True)
        agree, n_used, mdl = llm_check(all_txt, a.llm)
        print(f"  규칙↔LLM 일치율 {agree:.1%}  (n={n_used}, model={mdl})")

    ok_ci = lo <= 0 <= hi
    ok_gap = abs(diff) <= RATE_RULE
    ok_llm = (agree is None) or (agree >= LLM_MIN_AGREE)
    print("\n" + "=" * 60)
    print(f"판정  CI {'PASS' if ok_ci else 'FAIL'} · "
          f"차이 {'PASS' if ok_gap else 'FAIL'} · "
          f"일치율 {'PASS' if ok_llm else 'FAIL'}")
    if not ok_llm:
        print("=> 판정 불가. 규칙 사전을 신뢰할 수 없으므로 통과도 미통과도")
        print("   아니다 (§H-7). 사전을 고치는 것은 사후 선택이므로 금지.")
    elif ok_ci and ok_gap:
        print("=> 통과. 감성 구성은 생존과 연관되지 않는다 → 비율 지표는 안전.")
        print("   H-3(ABSA 입지 측면)으로 갈 수 있다.")
    else:
        print("=> 미통과. 양도 질도 편향된다 → 검색 기반 비정형은 여기서 종료.")
        print("   §13과 묶어 최종 기록한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
