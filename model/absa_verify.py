"""§H-9-⑤ — 2차 LLM 판정 일치율.

같은 프롬프트를 그대로 다시 던지면 temperature=0에서 거의 그대로 나오므로
안정성 검사가 되지 않는다. **항목 순서를 뒤집은 프롬프트**로 다시 판정해
같은 라벨이 나오는지 본다 — 순서에 흔들리면 판정이 그만큼 불안정하다는 뜻이다.

    python -m model.absa_verify --n 100
"""
import argparse
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from model.absa_run import MODEL
from pipeline.config import DB_PATH, ENV_PATH

SEED = 0
KEYS = ("crowd", "access", "visibility", "surround")

# absa_run.PROMPT 와 같은 정의, 항목 순서만 역순
PROMPT_REV = """다음은 한국어 음식점 관련 블로그 글의 일부다. 가게의 '위치·입지'에
관한 언급만 뽑아 JSON으로 출력하라. 맛·가격·서비스·메뉴·인테리어는 제외한다.

각 항목은 해당 언급이 있을 때만 값을 채우고, 없으면 null 로 둔다.
quote 가 비면 그 항목은 무시되므로, 근거가 되는 원문을 반드시 20자 이내로 인용하라.

{
 "surround":   {"dir": "lively"|"quiet"|"declining"|null, "quote": ""},  // 주변이 번화·한적·쇠퇴
 "visibility": {"dir": "visible"|"hidden"|null, "quote": ""},  // 눈에 잘 띈다·안쪽이라 안 보인다
 "access":     {"dir": "easy"|"hard"|null, "quote": ""},       // 찾아가기 쉽다·어렵다, 역/주차 접근성
 "crowd":      {"dir": "many"|"few"|null, "quote": ""}         // 사람/손님이 많다·적다, 붐빈다·한산하다
}

글: """


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    a = ap.parse_args()
    from openai import OpenAI
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    cli = OpenAI(api_key=env["OPENAI_API_KEY"])

    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT l.rowid_post, p.text, l.crowd, l.access, l.visibility, l.surround "
        "FROM absa_label l JOIN absa_post p ON p.rowid = l.rowid_post").fetchall()
    con.close()
    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(rows), size=min(a.n, len(rows)), replace=False)
    pick = [rows[i] for i in idx]
    print(f"2차 판정 {len(pick)}건 · model={MODEL} · 항목 순서 역순 프롬프트")

    def one(r):
        _rid, txt, *first = r
        try:
            resp = cli.chat.completions.create(
                model=MODEL, temperature=0, max_tokens=220,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": PROMPT_REV + txt[:700]}])
            d = json.loads(resp.choices[0].message.content)
            second = []
            for k in KEYS:
                v = d.get(k) or {}
                dr, q = v.get("dir"), (v.get("quote") or "").strip()
                second.append(dr if (dr and q) else None)
            return first, second
        except Exception:
            return None, None

    agree = defaultdict_counts = {k: [0, 0] for k in KEYS}
    both_n = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for first, second in ex.map(one, pick):
            if first is None:
                continue
            both_n += 1
            for k, f, s in zip(KEYS, first, second):
                agree[k][1] += 1
                if f == s:
                    agree[k][0] += 1

    print(f"\n{'항목':<14s}{'일치':>7s}{'건수':>7s}{'일치율':>9s}")
    tot_a = tot_n = 0
    for k in KEYS:
        a_, n_ = agree[k]
        tot_a += a_
        tot_n += n_
        print(f"{k:<14s}{a_:>7d}{n_:>7d}{(a_/n_ if n_ else 0):>9.1%}")
    overall = tot_a / tot_n if tot_n else 0
    print(f"\n전체 일치율 {overall:.1%}  (n={both_n}건 × {len(KEYS)}항목)")
    print(f"§H-9-⑤ 기준 0.70 → {'PASS' if overall >= 0.70 else 'FAIL — 판정 불가'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
