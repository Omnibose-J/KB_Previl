"""상호명 컨셉 추출 — 문자 n-gram TF-IDF + KMeans, 그리고 시대 누수 관문.

왜 키워드 사전이 아니라 군집인가. 사전을 사람이 만들면 결과를 보고 키워드를
고른 것이 되고(사후 선택), 실측으로 30개짜리 사전은 27.5%만 매칭했다. 군집은
정의를 실행 전에 고정할 수 있다 — 파라미터는 docs/unstructured-plan.md §3에
등록되어 있고 여기서 그대로 읽는다.

시대 누수 관문이 이 모듈의 존재 이유다. licence.bplcnm 은 개업 당시 이름이
아니라 상호 변경 시 갱신되는 현재값이다(LOCALDATA BPLCNM). 오래 살아남은
가게일수록 이름을 바꿀 기회가 많았으므로, "요즘 이름 스타일"이 생존과
상관되어 보인다 — 인과가 아니라 관측 시점의 차이다. 컨셉만으로 개업 연도를
맞힐 수 있으면 그 표현은 시대 신호를 담고 있다는 뜻이고, 그러면 쓸 수 없다.
관문에 걸리면 완화하지 않고 중단한다.

    python -m model.concept
"""
import argparse
import sqlite3
import sys

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedKFold

from pipeline.config import DB_PATH

# docs/unstructured-plan.md §3 에 등록된 값. 결과를 보고 바꾸지 않는다.
NGRAM = (2, 3)
MAX_FEATURES = 20000
MIN_DF = 20
K = 40
SEED = 0
N_INIT = 10

FIT_YEARS = (2005, 2022)      # 군집 학습에 쓰는 개업 연도. 시험기간을 넣으면 누수
ERA_BINS = [(2005, 2008), (2009, 2012), (2013, 2016), (2017, 2020), (2021, 2022)]
GATE_MACRO_F1 = 0.30          # §2-b. 초과하면 중단


def load(con):
    """(mgtno, 상호명, 개업연도) — 격자에 올라간 개업분 전체."""
    rows = con.execute(
        "SELECT mgtno, bplcnm, open_y FROM licence "
        "WHERE bplcnm IS NOT NULL AND trim(bplcnm) <> '' "
        "AND grid_id IS NOT NULL AND open_y IS NOT NULL"
    ).fetchall()
    return rows


def era_of(y):
    for i, (lo, hi) in enumerate(ERA_BINS):
        if lo <= y <= hi:
            return i
    return None


def fit_concepts(names_fit, names_all):
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=NGRAM,
                          max_features=MAX_FEATURES, min_df=MIN_DF)
    Xf = vec.fit_transform(names_fit)
    km = KMeans(n_clusters=K, random_state=SEED, n_init=N_INIT)
    km.fit(Xf)
    lab_all = km.predict(vec.transform(names_all))
    return vec, km, lab_all


def era_gate(labels, years):
    """컨셉만으로 개업 시대를 맞힐 수 있는가. macro-F1 이 낮아야 통과한다.

    시간 분할이 아니라 무작위 5-fold 인 것이 맞다 — 여기서 재는 것은 미래
    예측력이 아니라 '이 표현이 시대를 아는가'이기 때문이다.
    """
    eras = np.array([era_of(y) for y in years])
    ok = eras != None                                    # noqa: E711
    lab, era = labels[ok], eras[ok].astype(int)
    X = np.zeros((len(lab), K), dtype=np.float32)
    X[np.arange(len(lab)), lab] = 1.0
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    preds = np.zeros(len(era), dtype=int)
    for tr, te in skf.split(X, era):
        clf = LogisticRegression(max_iter=1000, multi_class="multinomial")
        clf.fit(X[tr], era[tr])
        preds[te] = clf.predict(X[te])
    return f1_score(era, preds, average="macro"), len(era)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=8, help="군집별 대표 상호명 표시 수")
    a = ap.parse_args()

    con = sqlite3.connect(DB_PATH)
    con.text_factory = bytes
    rows = [(m.decode("utf-8", "replace") if isinstance(m, bytes) else m,
             n.decode("utf-8", "replace") if isinstance(n, bytes) else n, y)
            for m, n, y in load(con)]
    con.text_factory = str
    print(f"상호명 {len(rows):,}건")

    fit_idx = [i for i, (_, _, y) in enumerate(rows) if FIT_YEARS[0] <= y <= FIT_YEARS[1]]
    names_all = [n for _, n, _ in rows]
    names_fit = [names_all[i] for i in fit_idx]
    print(f"군집 학습 대상 {len(names_fit):,}건 ({FIT_YEARS[0]}~{FIT_YEARS[1]} 개업)")

    print(f"TF-IDF char_wb{NGRAM} max_features={MAX_FEATURES} min_df={MIN_DF} → "
          f"KMeans K={K} n_init={N_INIT} ...", flush=True)
    vec, km, labels = fit_concepts(names_fit, names_all)
    print(f"어휘 {len(vec.vocabulary_):,}개 · 관성 {km.inertia_:.1f}")

    years = np.array([y for _, _, y in rows])
    # 관문은 군집 학습에 쓴 구간에서 판정한다
    m = np.array([FIT_YEARS[0] <= y <= FIT_YEARS[1] for y in years])
    f1, n_gate = era_gate(labels[m], years[m])
    print("\n=== 시대 누수 관문 ===")
    print(f"컨셉 → 개업연도 5구간, 무작위 5-fold macro-F1 = {f1:.4f}  (n={n_gate:,})")
    print(f"기준 ≤ {GATE_MACRO_F1} → {'PASS' if f1 <= GATE_MACRO_F1 else 'FAIL'}")

    # 군집 요약 — 정의는 이미 고정됐고, 이름 붙이기(해석)만 결과 후에 한다
    print("\n=== 군집 요약 (크기 상위) ===")
    order = np.argsort(-np.bincount(labels, minlength=K))
    for c in order[:K]:
        idx = np.where(labels == c)[0]
        if len(idx) == 0:
            continue
        sample = [names_all[i] for i in idx[:a.top]]
        print(f"  c{c:02d} n={len(idx):6,}  {' · '.join(sample)}")

    if f1 > GATE_MACRO_F1:
        print("\n관문 미통과 — Part A·D1 중단. 완화하지 않는다.")
        con.close()
        return 1

    con.execute("CREATE TABLE IF NOT EXISTS shop_concept "
                "(mgtno TEXT PRIMARY KEY, concept INTEGER NOT NULL)")
    con.execute("DELETE FROM shop_concept")
    con.executemany("INSERT INTO shop_concept(mgtno, concept) VALUES(?,?)",
                    [(rows[i][0], int(labels[i])) for i in range(len(rows))])
    con.commit()
    print(f"\nshop_concept {len(rows):,}행 저장")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
