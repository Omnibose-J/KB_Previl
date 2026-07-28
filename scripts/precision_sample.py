"""§I-19 PR 1 — gripe positive precision 검수 표본을 블라인드로 내보낸다.

**판정자에게 1차 라벨을 보여주지 않는다.** 특정 범주만 물으면 "추출기가 이 범주를
붙였다"는 사실이 새고 판정자가 확인 쪽으로 끌린다. 그래서 표본으로 뽑힌 글마다
**7범주 전부를 묻는다.** 정밀도는 나중에 채점할 때 1차가 붙인 범주만 골라서 센다.

1차가 본 것과 같은 본문을 보여준다 — `gripe_run.py:92` 가 `txt[:700]` 이다.
더 보여주면 다른 증거로 판정하는 것이 된다.

    python scripts/precision_sample.py
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import DB_PATH          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

SEED = 0
TRUNC = 700                                   # gripe_run.py:92 와 같아야 한다
OUT = Path(__file__).resolve().parent.parent / "scratch_precision"
BATCH = 110                                   # §I-15 와 같은 규모

# §I-19 등록 표본. 상한을 넘겨 등록하지 않았다.
N = {"wait": 60, "price": 60, "parking": 60, "seat": 60,
     "noise": 60, "service": 46, "clean": 28}
CATS = tuple(N)


def main():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rng = np.random.default_rng(SEED)

    # --- 범주별 predicted-positive 를 균등 무작위로
    picked = {}                               # rowid_post -> {1차가 붙인 범주}
    for c in CATS:
        rows = [r[0] for r in con.execute(
            f"SELECT rowid_post FROM gripe_label WHERE {c}=1 ORDER BY rowid_post")]
        n = min(N[c], len(rows))
        if n < N[c]:
            print(f"  {c}: 등록 {N[c]} > 실제 {len(rows)} — 전수 {n}건")
        idx = rng.choice(len(rows), size=n, replace=False)
        for i in idx:
            picked.setdefault(rows[i], set()).add(c)

    print(f"\n표본 쌍 {sum(len(v) for v in picked.values())} · 고유 글 {len(picked)}")

    # --- 본문·상호명 (라벨은 내보내지 않는다)
    ids = sorted(picked)
    qs = ",".join("?" * len(ids))
    meta = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        f"SELECT rowid, place, mgtno, text FROM absa_post WHERE rowid IN ({qs})", ids)}
    con.close()

    OUT.mkdir(exist_ok=True)
    (OUT / "truth.json").write_text(json.dumps(
        {str(k): sorted(v) for k, v in picked.items()}, ensure_ascii=False),
        encoding="utf-8")

    batches = [ids[i:i + BATCH] for i in range(0, len(ids), BATCH)]
    for bi, b in enumerate(batches, 1):
        items = []
        for rid in b:
            place, shop, txt = meta[rid]
            items.append({"id": str(rid), "지명": place, "상호명": shop,
                          "본문": (txt or "")[:TRUNC]})
        p = OUT / f"batch{bi}.json"
        p.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {p.name}  {len(items)}건")
    print(f"\n정답(1차 라벨)은 {OUT.name}/truth.json 에만 있다 — 판정자에게 주지 않는다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
