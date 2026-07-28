"""§I-21 B1 표본 — 확장 스니펫과 기준선 스니펫을 섞어 블라인드로 내보낸다.

판정자는 **어느 arm 에서 온 글인지 모르고**, §I-20 과 같이 7범주 전부를 판정한다.
어느 측면이 물음의 대상인지도 모른다.

    python scripts/bprobe_sample.py
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
SEED = 0
N_ASPECT, N_BASE, BATCH = 40, 60, 100
D = Path(__file__).resolve().parent.parent / "scratch_bprobe"
KW = {"wait": "웨이팅", "seat": "자리", "service": "친절", "clean": "청결",
      "price": "가격", "noise": "시끄러움", "parking": "주차"}
PASSED = ("seat", "service", "clean", "price", "noise", "parking")   # §I-21 B0


def main():
    raw = json.loads((D / "raw.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(SEED)

    pool = {a: [] for a in (*PASSED, "_base")}
    for r in raw:
        a = r["aspect"]
        if a not in pool or not r["items"]:
            continue
        for it in r["items"]:
            if not it["in_win"]:
                continue
            if a != "_base" and KW[a] not in it["text"]:
                continue          # 확장 arm 은 키워드가 실제로 담긴 글만
            pool[a].append((r["shop"], r["place"], it["text"]))

    picked, key = [], {}
    for a in (*PASSED, "_base"):
        want = N_BASE if a == "_base" else N_ASPECT
        uniq = list({t: (s, p, t) for s, p, t in pool[a]}.values())
        n = min(want, len(uniq))
        if n < want:
            print(f"  {a}: 풀 {len(uniq)} < 등록 {want} — 전수 {n}")
        for i in rng.choice(len(uniq), size=n, replace=False):
            shop, place, txt = uniq[i]
            pid = str(len(picked))
            picked.append({"id": pid, "지명": place, "상호명": shop, "본문": txt})
            key[pid] = a

    order = rng.permutation(len(picked))            # arm 이 섞이도록
    picked = [picked[i] for i in order]
    for i, p in enumerate(picked):
        p["id"] = str(i)
    key = {str(i): key[str(int(o))] for i, o in enumerate(order)}

    (D / "b1_key.json").write_text(json.dumps(key, ensure_ascii=False),
                                   encoding="utf-8")
    for bi in range(0, len(picked), BATCH):
        f = D / f"b1_batch{bi//BATCH + 1}.json"
        f.write_text(json.dumps(picked[bi:bi + BATCH], ensure_ascii=False, indent=1),
                     encoding="utf-8")
        print(f"  {f.name}  {len(picked[bi:bi+BATCH])}건")
    print(f"\n표본 {len(picked)}건 · arm 은 b1_key.json 에만 있다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
