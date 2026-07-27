"""밤새 돌리는 실험 큐. 순차 실행 — kb.db 는 동시 쓰기가 안 된다.

이 스크립트는 **판단하지 않는다.** 임계는 전부 각 검정 스크립트 안에 사전
등록된 값이고, 여기서는 명령을 순서대로 돌리고 종료 코드를 기록만 한다.

규칙(레인 A 브리핑):
- 실패하면 재시도 최대 3회, 그래도 안 되면 SKIP 사유와 함께 기록하고 다음으로
- 단계마다 시간 상한. 넘으면 중단하고 "측정 못 함"으로 기록
- 검정 스크립트의 exit 1 은 **고장이 아니라 판정 결과**다 — 재시도하지 않는다
- 모든 주장은 실행 명령 + 종료 코드와 함께

    python scripts/overnight.py              # 전부 실행
    python scripts/overnight.py --dry-run    # 순서·상한만 출력
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = ROOT / "docs" / "tracking" / "overnight"
PY = sys.executable
GLOBAL_CAP_MIN = 420          # 전체 7시간. 넘으면 남은 단계를 시작하지 않는다


def step(name, args, cap_min, retries=2, verdict=False, note=""):
    """verdict=True 면 exit!=0 을 판정 결과로 보고 재시도하지 않는다."""
    return dict(name=name, cmd=[PY, "-m"] + args, cap_min=cap_min,
                retries=0 if verdict else retries, verdict=verdict, note=note)


# H-4(시간대)는 §16에서 기각으로 확정됐다. 표본을 늘려 다시 돌리지 않는다 —
# 1/3 을 보고 나서 2/3 가 나올 때까지 키우는 것이 되기 때문이다. 큐에서 뺐다.
STEPS = [
    # --- 1단계: 가격대 (§I-9) — 표본 동결, 60개 지명 22,123건
    step("1. 가격 판정", ["model.price_run", "--judge", "--workers", "12",
                        "--cap", "400"], cap_min=90, note="§I-9"),
    step("2. 가격 2차 일치율", ["model.verify2", "--task", "price", "--n", "300"],
         cap_min=20, note="§I-9 — ±20% 이내면 일치, 기준 0.70"),
    step("3. I-9 검정", ["model.price_test"], cap_min=10, verdict=True,
         note="§I-9 임계 — CI 0 배제 AND rho>=0.30 · 단위 지명(§I-10-⑥)"),

    # --- 2단계: 경쟁자 약점 (§I-11) — 대조군 없음, 정확도만
    step("4. 불만 판정", ["model.gripe_run", "--judge", "--workers", "12",
                        "--cap", "400"], cap_min=90, note="§I-11"),
    step("5. 불만 2차 일치율", ["model.verify2", "--task", "gripe", "--n", "300"],
         cap_min=20, note="§I-11 — 범주별 0.70, 미달 범주만 비표시"),
    step("6. 불만 분포", ["model.gripe_run", "--stats"], cap_min=5, verdict=True),

    # --- 3단계: 게이트 재확인
    step("7. 누수 가드", ["model.test_leakage"], cap_min=10, verdict=True,
         note="기각된 신호가 DEPLOY 에 활성화되지 않았는지"),

    # --- 4단계: 커버리지 확대 — **검정이 전부 끝난 뒤에만**
    # 표본이 커진 뒤 위 검정을 다시 돌리면 두 번째 열람이 된다. 확대는 제품
    # 커버리지(§I-5, 60/247 지명)를 위한 것이고 재검정용이 아니다.
    step("8. 수집 확대 (지명당 80점포)", ["model.absa_run", "--collect", "--resume",
                                   "--workers", "6", "--n-shop", "80"],
         cap_min=180, note="§I-5 커버리지 — 재검정 금지"),
]


def run(s, logpath, env):
    """(exit_code, elapsed_sec, tail) — 상한 초과는 exit_code None."""
    t0 = time.time()
    with logpath.open("a", encoding="utf-8") as fh:
        fh.write(f"\n$ {' '.join(s['cmd'])}\n")
        fh.flush()
        try:
            p = subprocess.run(s["cmd"], cwd=ROOT, env=env, stdout=fh,
                               stderr=subprocess.STDOUT,
                               timeout=s["cap_min"] * 60)
            code = p.returncode
        except subprocess.TimeoutExpired:
            fh.write(f"\n[시간 상한 {s['cap_min']}분 초과 — 중단]\n")
            code = None
    tail = logpath.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
    return code, time.time() - t0, tail


def main():
    # 콘솔이 cp949 면 한글·em dash 에서 죽는다. 로그 파일은 별도로 utf-8 로 쓴다.
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.dry_run:
        tot = sum(s["cap_min"] for s in STEPS)
        for s in STEPS:
            mode = "판정(재시도 없음)" if s["verdict"] else f"재시도 {s['retries']}회"
            print(f"{s['name']:<22s} 상한 {s['cap_min']:>3d}분  {mode:<16s} {s['note']}")
        print(f"\n최악의 경우 합계 {tot}분 · 전체 상한 {GLOBAL_CAP_MIN}분")
        return 0

    LOGDIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    logpath = LOGDIR / f"run_{stamp}.log"
    summary = LOGDIR / f"summary_{stamp}.md"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

    t_start = time.time()
    lines = [f"# 밤샘 실험 결과 — {datetime.now():%Y-%m-%d %H:%M} 시작", "",
             f"전체 로그: `{logpath.name}`", "",
             "| 단계 | 명령 | 종료 | 소요 | 결과 |", "|---|---|---|---|---|"]
    results = []

    for s in STEPS:
        used = (time.time() - t_start) / 60
        if used + 1 > GLOBAL_CAP_MIN:
            lines.append(f"| {s['name']} | — | — | — | 전체 상한 초과로 미실행 |")
            results.append((s["name"], "미실행", "전체 상한"))
            continue
        print(f"\n{'='*66}\n{s['name']}  (상한 {s['cap_min']}분, 경과 {used:.0f}분)"
              f"\n$ {' '.join(s['cmd'])}", flush=True)

        code = None
        elapsed = 0.0
        tail = []
        for attempt in range(s["retries"] + 1):
            code, el, tail = run(s, logpath, env)
            elapsed += el
            if code == 0 or s["verdict"]:
                break
            if attempt < s["retries"]:
                print(f"  exit={code} — 재시도 {attempt+1}/{s['retries']}", flush=True)
                time.sleep(20)

        if code is None:
            verdict = f"시간 상한 {s['cap_min']}분 초과 — 측정 못 함"
        elif s["verdict"]:
            verdict = "통과" if code == 0 else f"기각/보류 (exit {code})"
        elif code == 0:
            verdict = "완료"
        else:
            verdict = f"SKIP — {s['retries']+1}회 모두 exit {code}"

        print(f"  → {verdict} · {elapsed/60:.1f}분", flush=True)
        for t in tail[-4:]:
            print(f"    {t}", flush=True)
        cmd_s = " ".join(s["cmd"][2:])
        lines.append(f"| {s['name']} | `{cmd_s}` | "
                     f"{'timeout' if code is None else code} | {elapsed/60:.1f}분 | {verdict} |")
        results.append((s["name"], verdict, s["note"]))
        summary.write_text("\n".join(lines), encoding="utf-8")

    lines += ["", f"전체 소요 {(time.time()-t_start)/60:.0f}분", "",
              "## 사전 등록 위치", ""]
    for n, v, note in results:
        if note:
            lines.append(f"- **{n}** — {v} · {note}")
    lines += ["", "판정은 각 스크립트에 등록된 임계로만 났다. 이 파일은 기록이고,",
              "임계를 바꿔 다시 돌린 것은 없다."]
    summary.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{'='*66}\n요약: {summary}")
    for n, v, _ in results:
        print(f"  {n:<22s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
