"""2차 판정 일치율 — demand · price · gripe 공용. 기준은 §H-9-⑤(0.70).

같은 프롬프트를 그대로 다시 던지면 안정성 검사가 되지 않는다. **항목 순서를
뒤집은 프롬프트**로 다시 판정해 같은 라벨이 나오는지 본다 — 순서에 흔들리면
판정이 그만큼 불안정하다는 뜻이다. `absa_verify.py` 가 쓴 방식을 그대로 따른다.

**1차와 같은 모델로 돌린다.** 다른 모델로 재판정하면 순서 민감도가 아니라
모델 간 불일치를 재게 된다. `demand_label` 은 gpt-4o-mini 로 판정됐고 H-4 는
§16에서 이미 기각으로 확정됐으므로 여기 대상이 아니다 — 그래서 demand 는 뺐다.

    python -m model.verify2 --task price  --n 300
    python -m model.verify2 --task gripe  --n 300
"""
import argparse
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from model.gripe_run import CATS
from model.llm import MODEL, DailyLimit, client, complete, new_fails
from model.price_run import parse as price_parse
from pipeline.config import DB_PATH

SEED = 0
THRESH = 0.70
PRICE_TOL = 0.20        # §I-9 — 금액은 ±20% 이내면 일치로 본다

# --- price: price_run.PROMPT 역순
PRICE_REV = """다음은 한국어 음식점 관련 블로그 글의 일부다. 글쓴이가 **1인당 얼마를
썼는지**만 뽑아 JSON으로 출력하라. 가게 위치·맛·분위기는 무시한다.

규칙:
- 1인분 가격, 인당 금액, 메뉴 하나 가격이 나오면 그 값을 쓴다.
- 총액만 있고 **인원이 명시된 경우에만** 나눈다. 인원을 모르면 null 이다.
  추측해서 나누지 마라.
- 금액이 여럿이면 대표 식사 1인분에 해당하는 값을 고른다.
- 근거 원문을 반드시 인용하라. 인용이 비면 그 값은 버려진다.

{
 "quote": "금액이 나온 원문 25자 이내 인용. 없으면 빈 문자열",
 "n_people": 숫자 또는 null,   // basis 가 divided 일 때만
 "basis": "unit"|"divided"|null,
   // unit = 1인분·인당 금액이 직접 있음, divided = 총액을 명시된 인원으로 나눔
 "per_person": 숫자(원) 또는 null
}

글: """

# --- gripe: gripe_run.PROMPT 역순
GRIPE_REV = """다음은 한국어 음식점 관련 블로그 글의 일부다. 글쓴이가 **불만을 말한
항목**만 뽑아 JSON으로 출력하라. 칭찬은 담지 마라.

각 항목은 불만이 있을 때만 true, 없거나 언급이 없으면 false 로 둔다.
quote 는 불만 하나에 대한 원문 25자 이내 인용이다. 불만이 하나도 없으면 빈 문자열.

{
 "quote":   "불만 원문 25자 이내 인용. 불만 없으면 빈 문자열",
 "parking": true|false,   // 주차가 어렵다·주차장이 없다
 "noise":   true|false,   // 시끄럽다·정신없다
 "price":   true|false,   // 가격이 비싸다·가격 대비 아쉽다
 "clean":   true|false,   // 위생·청결이 나쁘다
 "service": true|false,   // 응대가 불친절하다·느리다
 "seat":    true|false,   // 좌석이 좁다·불편하다·자리가 없다
 "wait":    true|false    // 대기·웨이팅이 길다, 줄 서야 한다
}

글: """


def eq_exact(a, b):
    return a == b


def eq_price(a, b):
    """둘 다 없으면 일치. 하나만 있으면 불일치. 둘 다 있으면 ±20%."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= PRICE_TOL * max(a, b)


TASKS = {
    "price": {
        "table": "price_label",
        "keys": ("per_person",),
        "prompt": PRICE_REV,
        "max_out": 400,
        "eq": eq_price,
    },
    "gripe": {
        "table": "gripe_label",
        "keys": CATS,
        "prompt": GRIPE_REV,
        "max_out": 400,
        "eq": eq_exact,
    },
}


def second(task, d):
    """2차 응답 → 1차 저장 형식과 같은 튜플."""
    if task == "price":
        got = price_parse(d)
        return (got[0] if got else None,)
    return tuple(1 if d.get(c) is True else 0 for c in CATS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=sorted(TASKS), required=True)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    cfg = TASKS[a.task]
    keys = cfg["keys"]

    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute(
            f"SELECT l.rowid_post, p.text, {','.join('l.'+k for k in keys)} "
            f"FROM {cfg['table']} l JOIN absa_post p ON p.rowid = l.rowid_post"
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"{cfg['table']} 읽기 실패 — {e}")
        return 1
    con.close()
    if not rows:
        print(f"{cfg['table']} 비어 있음 — 판정 보류")
        return 1

    cli = client()
    fails = new_fails()
    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(rows), size=min(a.n, len(rows)), replace=False)
    pick = [rows[i] for i in idx]
    print(f"task={a.task} · 2차 판정 {len(pick)}건 · model={MODEL} · 항목 순서 역순")

    def one(r):
        _rid, txt, *first = r
        raw = complete(cli, cfg["prompt"] + txt[:700], cfg["max_out"], fails)
        if raw is None:
            return None, None
        try:
            return tuple(first), second(a.task, json.loads(raw))
        except json.JSONDecodeError:
            fails["JSONDecodeError"] += 1
            return None, None

    eq = cfg["eq"]
    agree = {k: [0, 0] for k in keys}
    both_n = 0
    try:
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            for first, sec in ex.map(one, pick):
                if first is None:
                    continue
                both_n += 1
                for k, f, s in zip(keys, first, sec):
                    agree[k][1] += 1
                    if eq(f, s):
                        agree[k][0] += 1
    except DailyLimit as e:
        print(f"일일 한도 소진 — {e}")

    if fails:
        print("  실패 " + " · ".join(f"{k} {v:,}" for k, v in
                                    sorted(fails.items(), key=lambda kv: -kv[1])))
    if both_n < len(pick) * 0.5:
        print(f"2차 판정 성공 {both_n}/{len(pick)} — 절반 미만이라 측정 못 함")
        return 1

    print(f"\n{'항목':<12s}{'일치':>7s}{'건수':>7s}{'일치율':>9s}{'판정':>8s}")
    tot_a = tot_n = 0
    failed = []
    for k in keys:
        a_, n_ = agree[k]
        tot_a += a_
        tot_n += n_
        rate = a_ / n_ if n_ else 0.0
        ok = rate >= THRESH
        if not ok:
            failed.append(k)
        print(f"{k:<12s}{a_:>7d}{n_:>7d}{rate:>9.1%}{'PASS' if ok else 'FAIL':>8s}")
    overall = tot_a / tot_n if tot_n else 0.0
    print(f"\n전체 일치율 {overall:.1%}  (n={both_n}건 × {len(keys)}항목)")
    print(f"§H-9-⑤ 기준 {THRESH:.2f} → {'PASS' if overall >= THRESH else 'FAIL'}")
    if failed:
        # §I-11 — 범주별로 따로 판정한다. 하나가 흔들려도 나머지는 살린다.
        print(f"미달 항목(비표시 대상): {' · '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
