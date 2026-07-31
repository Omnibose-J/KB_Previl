"""Does the harness actually notice when the future leaks in?

A leakage guard nobody has seen fail is not a guard. This deliberately poisons
the feature set with post-opening information and asserts the detector fires
(RED), then asserts the real feature set does not trip it (GREEN).

Detector rule: an AUC at or above LEAK_AUC on a task where the strongest
no-learning baseline reaches ~0.56 is not a better model, it is an oracle.
"""
import sys

import numpy as np

from pipeline.db import connect_ro

from .cache import cached_split
from .osm import COLUMNS as _OSM_COLUMNS
from .train import CONFIRMED_TEST_YEARS, CONFIRMED_TRAIN_YEARS, fit_predict

LEAK_AUC = 0.90

# 배포 경로 — 여기서만 검사한다. 실험 모듈(concept·place·place_exp)은 당연히
# 실험 자산을 읽으므로 대상이 아니다.
DEPLOY_PATH = ("model/asof.py", "model/dataset.py", "model/evaluate.py",
               "model/train.py", "model/recommend.py", "model/recovery.py",
               "service/precompute.py")

# 스냅샷이라 as-of 재구성이 안 되는 것. asof.LEAKY 와 같은 종류이며 거기 빠져
# 있던 것을 여기서 채운다 (asof.py 는 캐시 지문의 입력이라 건드리면 전 스플릿이
# 무효화된다 — 가드는 가드 파일에 두는 편이 싸고 의미도 맞다).
SNAPSHOT_ONLY = {
    "trdar_flpop": "2026년 1분기 한 분기뿐 — lvpop_profile 과 같은 이유",
    # 후보로 재는 것은 정당하고 배포에 들어가는 것이 위반이다 (model/osm.py).
    **dict.fromkeys(_OSM_COLUMNS, "OSM 현재 스냅샷 — 2015년 도로가 2010년 개업에 붙는다"),
}

# 라운드 5(§11)에서 측정하고 배제한 원천. LEAKY 와 이유가 다르다 — 누수라서가
# 아니라 여섯 번 재고 기여가 없어서다. 섞어두면 나중에 "trend 는 누수라서 못
# 쓴다"는 잘못된 이해가 생긴다.
#
# 검사하는 것은 '이름이 등장하는가'가 아니라 '배포가 켜는가'다. `TREND` 상수
# 정의와 `with_trend=False` 기본값은 §10 재현에 필요해서 남아 있고, 지우면
# §6·§6-B 를 다시 돌릴 수 없다. **존재는 정당하고 활성화가 위반이다.**
REJECTED = {
    "trend": "검색 관심도 — 4회 측정 전부 기여 없음, 실제 유동인구와 ρ=0.079 (§11-E)",
    "mention": "점포 언급량 — 점 단위로 내려도 기여 없음 (§6-B)",
    "shop_concept": "상호명 컨셉 — 구성 변화가 성장을 예측 못 함, FDR 통과 0건 (§11-D)",
}

# 배포 경로에 있으면 곧바로 위반인 문자열.
#
# `asof.LEAKY` 의 키는 여기 넣지 않는다 — `grid_feature.food_store_cnt` 같은
# 점 표기는 실제 코드에 그 모양으로 나타나지 않는 **문서용 라벨**이고, 넣으면
# 금지 목록을 선언한 줄 자체가 위반으로 잡힌다. LEAKY 의 실질 가드는 3)이
# 이미 한다(피처가 as-of 문서에 등재됐는가).
#
# 옵션은 `with_*=True` 로 잡는다. 테이블명 `trend`·`mention` 을 그대로 쓰면
# `with_trend` 같은 정당한 식별자에 걸린다. 고유한 이름만 테이블로 잡는다.
ACTIVATIONS = ("with_trend=True", "with_mention=True",
               "shop_concept") + tuple(SNAPSHOT_ONLY)


def scan_deploy_path(names):
    """배포 경로 소스에서 주어진 문자열을 찾는다. -> [(파일, 줄, 문자열)]"""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    hits = []
    for rel in DEPLOY_PATH:
        p = root / rel
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]          # 주석에 이름을 적는 것은 허용
            for nm in names:
                if nm in code:
                    hits.append((rel, i, nm))
    return hits


def auc_of(train, test, kind="logit"):
    from sklearn.metrics import roc_auc_score
    p, _ = fit_predict(kind, train, test)
    return roc_auc_score(test[1], p)


def poison(split, y):
    """Inject a feature derived from the label - i.e. from after the opening."""
    X, yy, meta = split
    out = []
    rng = np.random.default_rng(0)
    for f, lab in zip(X, yy):
        g = dict(f)
        # 'months the shop actually lasted' is only knowable after the fact
        g["site_area"] = float(lab) * 100.0 + rng.normal(0, 5)
        out.append(g)
    return (out, yy, meta)


def recovery_cutoff_guard():
    """A successor opening in the closure month must not alter M2 features."""
    from .asof import AsOf
    from .recovery import features_before_closure

    grid_id = "100_100"
    uptae = "한식"
    close_ym = 202301
    base = [
        (grid_id, uptae, 2020 * 12 + 1, 2022 * 12 + 11, 50.0),
    ]
    future_successor = (
        grid_id,
        uptae,
        2023 * 12 + 1,
        None,
        75.0,
    )
    before = features_before_closure(
        AsOf(base), grid_id, uptae, close_ym
    )
    poisoned = features_before_closure(
        AsOf([*base, future_successor]), grid_id, uptae, close_ym
    )
    return before == poisoned


def main():
    con = connect_ro()
    train, test = cached_split(con, CONFIRMED_TRAIN_YEARS, CONFIRMED_TEST_YEARS, 3)

    print("1) RED — 미래 정보를 주입하면 탐지되어야 한다")
    ptr = poison(train, train[1])
    pte = poison(test, test[1])
    a_leak = auc_of(ptr, pte)
    red_ok = a_leak >= LEAK_AUC
    print(f"   오염 피처 AUC {a_leak:.4f}  (탐지 임계 {LEAK_AUC})")
    print(f"   -> {'탐지됨 PASS' if red_ok else '탐지 실패 FAIL — 가드가 무력하다'}")

    print("\n2) GREEN — 정상 피처는 탐지되지 않아야 한다")
    a_clean = auc_of(train, test)
    green_ok = a_clean < LEAK_AUC
    print(f"   정상 피처 AUC {a_clean:.4f}")
    print(f"   -> {'정상 PASS' if green_ok else 'FAIL — 정상 피처가 오라클 수준, 누수 의심'}")

    print("\n3) 피처 목록에 금지 소스가 없는지 확인")
    from .asof import FEATURES
    from .feature_gate import FAMILIES
    from .recovery import RECOVERY_FEATURES
    from .robustness import FEATURE_SETS
    from .train import DEPLOY, G2X, TIER1, TIER2, TIER3
    # 손으로 나열하지 않고 실제 등록부에서 끌어온다 — FEATURE_SETS 는 적합하는
    # 세트, FAMILIES 는 편입 심사가 거르는 후보군이다.
    covered = sorted(
        set().union(*(set(c) for c in FEATURE_SETS.values()))
        | set().union(*(set(cols) for cols, _ in FAMILIES.values()))
        | set(RECOVERY_FEATURES)
        | set(G2X)
        | set(TIER1 + TIER2 + TIER3)
    )
    # 배포되는 세트는 둘이다 — 순위 모델의 DEPLOY 와 승계 서빙의 RECOVERY.
    deployed = set(DEPLOY) | set(RECOVERY_FEATURES)
    unknown = [n for n in covered if n not in FEATURES and n not in SNAPSHOT_ONLY]
    deployed_snapshot = sorted(set(SNAPSHOT_ONLY) & deployed)
    print(f"   검사 대상 {len(covered)}개 (적합 세트·심사 후보군·복구·G2X·Tier1~3) 중 "
          f"as-of 문서 미등재: {unknown or '없음'}")
    print(f"   시점 재구성 불가 {len(SNAPSHOT_ONLY)}개 — 배포 세트 침투: "
          f"{deployed_snapshot or '없음'}")
    doc_ok = not unknown and not deployed_snapshot

    # 4) 여기까지는 '피처 이름'만 봤다. 배제된 원천이 배포에서 실제로 켜지는
    #    것은 별개의 사고이고, 이전에는 문구로만 단언하고 확인하지 않았다.
    print("\n4) 배제 원천이 배포에서 켜지는지 확인")
    from .asof import MENTION_FEATURES
    from .train import TREND

    tainted = set(TREND) | set(MENTION_FEATURES)
    in_deploy = sorted(tainted & set(covered))
    hits = scan_deploy_path(ACTIVATIONS)
    print(f"   배제 원천 유래 피처 {len(tainted)}개 — 배포/후보 세트 침투: "
          f"{in_deploy or '없음'}")
    print(f"   배포 경로 {len(DEPLOY_PATH)}개 파일 · 활성화 문자열 "
          f"{len(ACTIVATIONS)}종 검사: ", end="")
    if hits:
        print()
        for f, ln, nm in hits:
            print(f"   FAIL {f}:{ln}  '{nm}'")
    else:
        print("흔적 없음")
    src_ok = not hits and not in_deploy
    print(f"   -> {'PASS' if src_ok else 'FAIL'}"
          f"   (존재는 정당하고 활성화가 위반 — §10 재현이 옵션을 쓴다)")

    print("\n5) M2 폐업월 직후 승계행 차단")
    recovery_ok = recovery_cutoff_guard()
    print("   close_ym 승계행 poison 전후 피처: "
          f"{'불변 PASS' if recovery_ok else '변경 FAIL — 미래 승계 누수'}")

    ok = red_ok and green_ok and doc_ok and src_ok and recovery_ok
    print("\n" + "=" * 46)
    print(f"누수 가드 {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
