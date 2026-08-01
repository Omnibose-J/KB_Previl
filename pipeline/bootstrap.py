"""Cold start: an empty database to a serving one, in the order that works.

The repository ships code only - kb.db, pipeline/cache/ and model/.cache/ are
all gitignored and no trained model artifact is tracked. A reviewer who clones
this repo therefore has to build everything, and `service.precompute` retrains
the ranker as part of that, so there is no artifact-distribution path to worry
about.

Two things this fixes over `pipeline.run`:

  * `run.py` stops after features and never builds grid_score, so a database it
    produces serves an empty recommendation list.
  * `build_features` reads grid_sgis and sgis_dong (features.py:167-173), so the
    census step has to precede it. `run.py` has no census step at all, which
    leaves corp_cnt NULL for every cell on a cold database.

Every step is skipped when its output table already has rows, so a run that
died on an exhausted API quota can be resumed by repeating the same command.
"""
import argparse
import os
import sqlite3
import subprocess
import sys
import time

from .config import (CACHE_DIR, DEFAULT_QUARTER, DB_PATH, ENV_PATH,
                     SEOUL_DAILY_BUDGET, load_env)
from .db import connect_ro, init


REQUIRED_ENV_KEYS = (
    ("SEOUL_OPEN_API_KEY", "서울 열린데이터 수집에 필요합니다."),
    ("KAKAO_REST_API_KEY", "격자 중심을 행정동으로 역지오코딩할 때 필요합니다."),
    ("SGIS_CONSUMER_KEY", "SGIS 센서스 자료 인증에 필요합니다."),
    ("SGIS_CONSUMER_SECRET", "SGIS 센서스 자료 인증 비밀키로 필요합니다."),
)
OPTIONAL_ENV_KEY = "DATA_GO_KR_SERVICE_KEY"


# Tables the product actually reads. The fingerprint compares these and nothing
# else: an experiment table appearing or disappearing must not look like drift.
SERVING_TABLES = (
    "grid", "grid_feature", "grid_sgis", "grid_access", "grid_concept",
    "grid_score", "succession_score", "score_meta", "licence", "licence_rest",
    "store", "station", "trdar_sales", "trdar_store",
)

# Rejected experiments. Recorded in docs/model-findings.md; the data is dead
# weight. bootstrap never creates these, so a cold database simply lacks them.
DEAD_TABLES = (
    # 비정형 — nine rejections (CLAUDE.md, model-findings §18·§19)
    "mention", "mention_shop", "trend", "absa_post", "absa_label",
    "gripe_label", "price_label", "uptae_label", "demand_label",
    "guest_label", "merit_label", "text_profile",
    # 실거래가 — rejected §12
    "realprice", "realprice_done",
    # written by pipeline.sgis, read by nothing
    "sgis_jipgyegu",
)


class Step:
    def __init__(self, name, produces, run, note=""):
        self.name = name
        self.produces = produces      # table that proves the step already ran
        self.run = run
        self.note = note


def _rows(table):
    """Row count, or None when the database or the table does not exist yet."""
    try:
        con = connect_ro()
    except sqlite3.Error:
        return None
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _module(*argv):
    """Run a module through its own CLI so the documented command and what
    bootstrap does can never diverge."""
    def go(_args):
        cmd = [sys.executable, "-m", *argv]
        print(f"  $ {' '.join(cmd[1:])}", flush=True)
        rc = subprocess.call(cmd)
        if rc != 0:
            raise SystemExit(f"'{' '.join(argv)}' 실패 (exit {rc})")
    return go


def _collect(args):
    # SEMAS 도 함께 받는다. 이것이 없으면 store 가 비고, consistency 의
    # crosssource 검사가 상관 r=0 으로 실패한다 — 게이트 4종을 통과한 DB 를
    # 만드는 것이 이 스크립트의 계약이므로 선택 항목일 수 없다.
    # 쿼터는 서울 열린데이터와 별개(data.go.kr)라 일일 900콜에 영향이 없다.
    from .collect import collect_semas, collect_seoul
    collect_seoul(args.quarter, force=args.force)
    if load_env().get(OPTIONAL_ENV_KEY):
        collect_semas()
    else:
        print(f"  [건너뜀] SEMAS — {OPTIONAL_ENV_KEY} 없음. "
              "consistency 의 crosssource 가 실패한다.")


def _normalize(_args):
    from .normalize import (flag_succession, norm_licence, norm_lvpop,
                            norm_store, norm_trdar)
    con = init()
    norm_licence(con)
    flag_succession(con)
    norm_trdar(con)
    norm_lvpop(con)
    norm_store(con)


def _cohort(_args):
    from .cohort import compute
    con = init()
    compute(con)
    # consistency 의 succession 검사는 두 변형을 조인해 «승계를 빼면 생존율이
    # 올라간다» 를 확인한다. 제외판을 안 만들면 조인 결과가 비어 검사가 실패한다.
    compute(con, exclude_succession=True)


def _grid(_args):
    from .features import build_grid
    build_grid(init())


def _geocode(_args):
    from .geocode import run
    run()


def _features(args):
    from .features import build_features
    build_features(init(), args.quarter)


def _party(args):
    """수집과 적재를 한 단계로 묶는다 — 수집만 하고 적재를 잊으면 캐시에는
    데이터가 있는데 서빙은 비어 있고, 그 상태가 «수집 안 됨» 과 구분되지 않는다.
    수집은 이어받기 되므로 중간에 끊겨도 같은 명령을 다시 치면 된다."""
    _module("model.party", "--full")(args)
    _module("model.party", "--load")(args)


STEPS = [
    Step("schema", None, lambda a: init(),
         "테이블 생성"),
    Step("collect", None, _collect,
         "서울 열린데이터 → pipeline/cache/*.jsonl (일일 900콜)"),
    Step("normalize", "licence", _normalize,
         "인허가·상권·생활인구·점포 적재"),
    # 휴게음식점. concept_mix 와 service.api 가 licence_rest 를 읽으므로
    # concept_mix 보다 앞이어야 한다. 캐시만 있으면 되고 다른 표에 기대지 않아
    # normalize 바로 뒤에 둔다 — 두 인허가 표가 같이 자리 잡는다.
    Step("tier2", "licence_rest", _module("model.tier2"),
         "휴게음식점 적재 — 카페·베이커리·패스트푸드"),
    Step("cohort", "cohort_survival", _cohort,
         "개업 코호트 생존율"),
    Step("grid", "grid", _grid,
         "100m 격자 생성"),
    Step("geocode", None, _geocode,
         "격자 중심 역지오코딩 → 행정동 (KAKAO, 격자 23,573)"),
    Step("sgis", "sgis_dong", _module("pipeline.sgis", "--both"),
         "SGIS 센서스 — features 보다 먼저여야 한다"),
    Step("sgis_match", "grid_sgis", _module("pipeline.sgis_match"),
         "행정동 폴리곤 ↔ 격자 매칭"),
    Step("features", "grid_feature", _features,
         "격자 피처 — grid_sgis·sgis_dong 를 읽는다"),
    Step("access", "grid_access", _module("pipeline.access"),
         "지하철 접근성"),
    Step("addr_history", "addr_tenancy", _module("pipeline.addr_history", "--build"),
         "주소 단위 점유 이력 → 승계 라벨"),
    Step("concept", "shop_concept", _module("model.concept"),
         "상호명 군집"),
    Step("concept_mix", "grid_concept", _module("model.concept_mix"),
         "격자별 컨셉 구성"),
    Step("precompute", "grid_score", _module("service.precompute"),
         "순위 모델 학습 + 격자 점수 — 가장 긴 단계"),
    # service/api.py:65-68 의 GRADE_AREA_KEYS 와 1·3·5년 생존 표는 여기서만
    # 나온다. 빼면 /meta 가 «메타 없음» 으로 죽는다 — precompute 가 쓰는 키와
    # 겹치지 않으므로 순서는 precompute 뒤 아무 데나 상관없다.
    Step("ui_curves", None, _module("model.ui_curves", "--write"),
         "등급×면적대 벤치마크 + 1·3·5년 생존 표 → score_meta"),
    # recovery.py:328 은 grid_score 에서 (격자, 업태) 쌍을 읽어 승계 확률을
    # 채운다. 비어 있으면 «grid_score has no serving candidates» 로 죽으므로
    # precompute 뒤여야 한다. 반대 방향 의존은 없다 —
    # precompute 는 succession_score 를 읽지 않는다.
    Step("succession", "succession_score", _module("model.recovery", "--build-serving"),
         "승계 확률 m2 — grid_score 의 쌍을 채운다"),
    # 마지막에 둔다. 방문객 동반자는 점수에 들어가지 않고(§J-1-④) 서빙이
    # trdar_party 를 직접 읽으므로 뒤따라 재실행할 단계가 없다. 중간에 넣으면
    # 이 단계를 갱신할 때마다 precompute(가장 긴 단계)가 헛돈다.
    # trdar_area 만 있으면 되므로 normalize 뒤 어디든 놓을 수 있다.
    Step("party", "trdar_party", _party,
         "방문객 동반자 수집·적재 — 상권 1,650개, 약 1시간 (§J-1)"),
]

GATES = (
    ("pipeline.verify",), ("pipeline.consistency",),
    ("model.test_leakage",), ("model.asof", "--selftest-cut"),
)


def _configure_cli_output():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def preflight():
    """Check cold-start prerequisites without making network calls."""
    print("콜드스타트 사전 점검")
    failures = 0

    if ENV_PATH.is_file():
        print(f"[PASS] .env: {ENV_PATH} — API 자격 증명을 읽는 파일입니다.")
        try:
            env = load_env()
        except OSError:
            env = {}
            failures += 1
            print("[FAIL] .env 읽기 — 파일을 읽을 수 없습니다.")
    else:
        env = {}
        failures += 1
        print(f"[FAIL] .env: {ENV_PATH} — 콜드스타트 필수 키 파일이 없습니다.")

    for key, reason in REQUIRED_ENV_KEYS:
        if env.get(key):
            print(f"[PASS] {key} — {reason} 값 유효성은 확인하지 않습니다.")
        else:
            failures += 1
            print(f"[FAIL] {key} — {reason} .env에 값이 없습니다.")

    # 예전엔 «--semas 에만 필요» 라고 적혀 있었지만, 이 키가 없으면 store 가
    # 비고 consistency 의 crosssource(인허가 밀도 ↔ 소상공인 밀도 상관)가
    # r=0 으로 실패한다. 완주는 되지만 게이트 4종 통과는 안 된다.
    if env.get(OPTIONAL_ENV_KEY):
        print(f"[PASS] {OPTIONAL_ENV_KEY} — SEMAS 수집. 없으면 consistency 의 "
              "crosssource 가 실패합니다.")
    else:
        print(f"[경고] {OPTIONAL_ENV_KEY} 미설정 — 완주는 되지만 "
              "consistency 의 crosssource 검사가 실패합니다.")

    if DB_PATH.exists():
        db_writable = DB_PATH.is_file() and os.access(DB_PATH, os.W_OK)
    else:
        parent = DB_PATH.parent
        db_writable = (
            parent.is_dir()
            and os.access(parent, os.W_OK)
        )
    if db_writable:
        print(
            f"[PASS] KB_DB: {DB_PATH} — "
            "콜드스타트가 SQLite DB를 생성·갱신할 수 있습니다."
        )
    else:
        failures += 1
        print(
            f"[FAIL] KB_DB: {DB_PATH} — "
            "SQLite DB를 생성·갱신할 수 있는 경로가 아닙니다."
        )

    # 캐시가 있으면 그만큼 호출을 안 쓴다. 어느 것이 있는지 낱개로 알려준다 —
    # licence.jsonl 하나만 보고 «캐시 있음» 이라 하면 휴게음식점 147콜이
    # 남아 있는데도 준비된 줄로 읽힌다.
    # 실측 2026-07-29, 빈 캐시로 `collect --dry-run` (서비스당 총건수 1콜).
    # 합계 857 로 일일 한도 900 에 여유가 43 밖에 없다.
    CACHE_CALLS = {
        "licence.jsonl": 536,
        "licence_rest.jsonl": 147,
        "trdar_area.jsonl": 2,
        f"trdar_sales_{DEFAULT_QUARTER}.jsonl": 22,
        f"trdar_store_{DEFAULT_QUARTER}.jsonl": 76,
        f"trdar_flpop_{DEFAULT_QUARTER}.jsonl": 2,
        "lvpop.jsonl": 72,
    }
    if not CACHE_DIR.is_dir():
        print(f"[안내] KB_CACHE: {CACHE_DIR} — 캐시 디렉터리 없음, 전량 수집 필요")
        need = sum(CACHE_CALLS.values())
    else:
        have = [n for n in CACHE_CALLS if (CACHE_DIR / n).is_file()]
        need = sum(v for n, v in CACHE_CALLS.items() if n not in have)
        print(f"[안내] KB_CACHE: {CACHE_DIR} — 캐시 {len(have)}/{len(CACHE_CALLS)}종")
        for name, calls in CACHE_CALLS.items():
            mark = "있음" if name in have else f"없음 (약 {calls}콜)"
            print(f"         {name:<32} {mark}")
    print(f"[안내] 서울 열린데이터 예상 소요: 약 {need}콜 "
          f"(일일 한도 {SEOUL_DAILY_BUDGET}). 넘으면 다음 날 같은 명령을 다시 치면 "
          "이어서 받는다.")

    if db_writable:
        try:
            from .seoul_api import remaining
            remaining_calls = remaining()
        except Exception as exc:
            failures += 1
            print(
                "[FAIL] 서울 API 잔여 호출 — "
                f"로컬 호출 이력을 읽지 못했습니다 ({type(exc).__name__})."
            )
        else:
            if remaining_calls > 0:
                print(
                    f"[PASS] 서울 API 잔여 호출: {remaining_calls}회 — "
                    "오늘 서울 열린데이터 수집에 사용할 쿼터입니다."
                )
            else:
                failures += 1
                print(
                    "[FAIL] 서울 API 잔여 호출: 0회 — "
                    "오늘 collect를 완주할 호출 쿼터가 없습니다."
                )
    else:
        print(
            "[확인 불가] 서울 API 잔여 호출 — "
            "쓰기 가능한 KB_DB가 먼저 필요합니다."
        )

    if failures:
        print(f"사전 점검 FAIL — {failures}개 필수 조건을 확인하세요.")
        return 1
    print("사전 점검 PASS")
    return 0


def fingerprint():
    print(f"DB {DB_PATH}")
    con = connect_ro()
    try:
        for t in SERVING_TABLES:
            try:
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.Error:
                n = None
            print(f"  {t:<20} {'—' if n is None else format(n, ',')}")
        print("  ---- score_meta headline ----")
        for k in ("rank_model", "rank_features", "rank_train_years",
                  "rank_test_years"):
            try:
                row = con.execute(
                    "SELECT v FROM score_meta WHERE k=?", (k,)).fetchone()
            except sqlite3.Error:
                row = None
            print(f"  {k:<20} {row[0] if row else '—'}")
    finally:
        con.close()


def plan():
    """단계 목록과 각 단계가 이미 채워졌는지 출력한다."""
    print(f"단계 {len(STEPS)}종")
    for i, step in enumerate(STEPS, 1):
        n = _rows(step.produces) if step.produces else None
        state = "완료" if n else ("미실행" if step.produces else "매번 실행")
        count = f"{n:,}행" if n else ""
        print(f"  [{i:>2}] {step.name:<12} {state:<6} {count:<12} {step.note}")
    return 0


def prune(dry_run):
    present = []
    con = connect_ro()
    try:
        for t in DEAD_TABLES:
            row = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (t,)).fetchone()
            if row:
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                present.append((t, n))
    finally:
        con.close()
    if not present:
        print("지울 것이 없습니다 — 기각된 실험 테이블이 이미 없습니다.")
        return 0

    before = DB_PATH.stat().st_size
    print(f"삭제 대상 {len(present)}개 · 현재 파일 {before / 1024**2:,.0f} MB")
    for t, n in present:
        print(f"  {t:<20} {n:>10,} 행")
    if dry_run:
        print("\n--dry-run — 아무것도 지우지 않았습니다.")
        return 0

    con = init()
    for t, _ in present:
        con.execute(f'DROP TABLE IF EXISTS "{t}"')
    con.commit()
    con.execute("VACUUM")
    con.close()
    after = DB_PATH.stat().st_size
    print(f"\n완료 — {before / 1024**2:,.0f} MB → {after / 1024**2:,.0f} MB "
          f"({(before - after) / 1024**2:,.0f} MB 회수)")
    return 0


def main():
    _configure_cli_output()
    ap = argparse.ArgumentParser(
        description="빈 DB에서 서비스 가능한 DB까지 — 단계: "
                    + " → ".join(s.name for s in STEPS))
    ap.add_argument("--quarter", default=DEFAULT_QUARTER)
    ap.add_argument("--skip-collect", action="store_true",
                    help="캐시된 jsonl 만 쓰고 API 를 호출하지 않는다")
    ap.add_argument("--from", dest="start", metavar="STEP",
                    help="이 단계부터 재개 (쿼터 소진 후 이어하기)")
    ap.add_argument("--only", metavar="STEP", help="이 단계만 실행")
    ap.add_argument("--force", action="store_true",
                    help="출력 테이블이 이미 차 있어도 다시 실행")
    ap.add_argument("--refresh", metavar="STEP",
                    help="갱신: 이 단계부터 끝까지 다시 실행한다 "
                         "(= --from STEP --force). 뒤따르는 단계가 자동으로 "
                         "따라온다 — STEPS 가 의존 순서다")
    ap.add_argument("--gates", action="store_true", help="마지막에 게이트 4종 실행")
    ap.add_argument("--fingerprint", action="store_true",
                    help="제품 경로 테이블 행수와 score_meta 헤드라인만 출력")
    ap.add_argument("--prune", action="store_true",
                    help="기각된 실험 테이블을 지우고 VACUUM (파괴적)")
    ap.add_argument("--dry-run", action="store_true", help="--prune 과 함께")
    ap.add_argument("--preflight", action="store_true",
                    help="긴 단계나 네트워크 호출 없이 콜드스타트 조건 점검")
    ap.add_argument("--plan", action="store_true",
                    help="단계 목록과 완료 여부만 출력")
    a = ap.parse_args()

    # 갱신은 새 실행 경로가 아니라 이름이다. --from + --force 가 이미 그 동작인데
    # 그 조합이 «갱신» 으로 읽히지 않아, 다시 눌러도 전부 건너뛰는 것을 정상으로
    # 오해하기 쉽다. 동작을 늘리지 않고 의도만 이름 붙인다.
    if a.refresh:
        if a.start or a.only:
            raise SystemExit("--refresh 는 --from·--only 와 함께 쓸 수 없다")
        a.start, a.force = a.refresh, True

    if a.preflight:
        return preflight()
    if a.plan:
        return plan()
    if a.fingerprint:
        fingerprint()
        return 0
    if a.prune:
        return prune(a.dry_run)

    names = [s.name for s in STEPS]
    # --refresh 는 a.start 로 접히므로, 그대로 두면 --refresh 를 친 사람에게
    # «--from 알 수 없는 단계» 라고 답한다. 치지도 않은 플래그를 고치라는 말이 된다.
    start_label = "--refresh" if a.refresh else "--from"
    for label, value in ((start_label, a.start), ("--only", a.only)):
        if value and value not in names:
            raise SystemExit(f"{label} 알 수 없는 단계 '{value}' — {', '.join(names)}")

    t0 = time.time()
    started = a.start is None
    for i, step in enumerate(STEPS, 1):
        if a.only and step.name != a.only:
            continue
        if not a.only:
            started = started or step.name == a.start
            if not started:
                continue
        if step.name == "collect" and preflight() != 0:
            return 1
        if step.name == "collect" and a.skip_collect:
            print(f"[{i}/{len(STEPS)}] {step.name} — 건너뜀 (--skip-collect)")
            continue

        n = _rows(step.produces) if step.produces else None
        if n and not a.force and not a.only:
            print(f"[{i}/{len(STEPS)}] {step.name} — 건너뜀 "
                  f"({step.produces} {n:,}행 존재)")
            continue

        print(f"[{i}/{len(STEPS)}] {step.name} — {step.note}", flush=True)
        t = time.time()
        step.run(a)
        print(f"      {time.time() - t:.0f}s")

    failed = []
    if a.gates:
        print("\n게이트 4종")
        # 첫 실패에서 멈추지 않는다. 캐시로 재구축하면 verify 의 counts 가 거의
        # 항상 어긋나는데(아래), 거기서 끊으면 나머지 셋이 통과하는지조차 알 수
        # 없다 — 검토자가 «어디까지 멀쩡한가» 를 한 번에 봐야 한다.
        for gate in GATES:
            print(f"\n  $ python -m {' '.join(gate)}", flush=True)
            if subprocess.call([sys.executable, "-m", *gate]) != 0:
                failed.append(" ".join(gate))

        print("\n" + "=" * 56)
        if not failed:
            print("게이트 4/4 PASS")
        else:
            print(f"게이트 {len(GATES) - len(failed)}/{len(GATES)} PASS  "
                  f"실패: {', '.join(failed)}")
            if failed == ["pipeline.verify"]:
                print(
                    "\n  verify 만 실패했다면 counts 검사일 가능성이 크다. 그 검사는\n"
                    "  적재 건수를 «라이브 API 총건수» 와 대조하므로, 캐시로 재구축한\n"
                    "  DB 는 캐시를 받은 뒤 원천에 늘어난 만큼 어긋난다. 수집을 포함한\n"
                    "  진짜 콜드런에서는 통과한다(README «알아둘 것»).\n"
                    "  캐시를 지우고 collect 부터 다시 받으면 확인된다."
                )

    print(f"\n총 {time.time() - t0:.0f}s")
    fingerprint()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
