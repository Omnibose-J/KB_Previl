# 수용 기준: 콜드런 파이프라인 + DB 정리 (제출 대비)

목표: 심사위원이 **코드만 받은 상태**(`git clone` + `.env`)에서 명령 하나로 DB를
만들고 서비스를 띄울 수 있다. 그 과정에서 기각된 실험의 잔여 데이터는 재생성되지
않는다.

## 확정 사실 (조사 2026-07-29)

- 제출물에 데이터가 없다 — `kb.db`·`pipeline/cache/`·`model/.cache/` 전부 gitignore.
  추적 파일 211개 5.3MB, **추적되는 모델 아티팩트 0개**.
- `service/precompute.py`가 `cached_split` → `fit_predict`로 **모델을 직접 학습**한다.
  따라서 "제로 → 서비스"는 재학습을 이미 포함하며, 별도 아티팩트 배포 경로가 없다.
- `pipeline/run.py`는 collect→normalize→cohort→grid→geocode→features→verify까지만
  돈다. **빠진 것**: `sgis`(+`sgis_match`) · `access` · `addr_history` ·
  `model.recovery` · `model.concept`/`concept_mix` · `service.precompute`.
  현행 `run.py`만으로는 `grid_score`가 없어 추천이 뜨지 않는다.
- DB 460MB / 39테이블 중 제품 경로 13개.

## 완료 조건

### 1. 콜드런 진입점

- [x] `python -m pipeline.bootstrap --help`가 전 구간 단계를 나열한다
  → verify: `python -m pipeline.bootstrap --help` → exit 0 (16단계)
- [x] 빈 DB 경로를 주면 스키마부터 `grid_score`까지 만들고 0으로 끝난다
  → verify: `$env:KB_DB='...\kb-cold.db'; python -m pipeline.bootstrap --skip-collect --gates`
  → 15단계 완주. 캐시 기준 약 5분 + `ui_curves` 895초
- [x] 각 단계가 «건너뜀/실행» 사유를 출력한다 (이미 채워진 테이블은 재실행하지 않음)
  → verify: `--from` 재개가 3회 동작 (addr_history · concept · ui_curves)
- [x] 중간 실패 시 다음 단계로 넘어가지 않고 그 지점에서 비0으로 끝난다
  → verify: 실측 3회 — `score_meta` 부재 · `grid_score` 부재 · 게이트 실패 전부 그 자리에서 exit 1

**콜드런이 찾아낸 결함 (전부 «채워진 DB에서는 안 드러나는» 종류)**

| # | 결함 | 조치 |
|---|---|---|
| 1 | `run.py`가 `grid_score`를 안 만듦 → 추천이 빈 목록 | bootstrap에 `precompute` 추가 |
| 2 | SGIS 단계 부재 → `build_features`가 센서스 없이 돎 | `sgis`·`sgis_match`를 `features` 앞에 |
| 3 | `score_meta` 소유자가 `service.precompute` → `addr_history`가 먼저 도는데 테이블이 없음 | 공유 스키마(`pipeline/db.py`)로 이관 |
| 4 | `succession`이 `precompute`보다 앞 → `grid_score has no serving candidates` | 순서 반전 |
| 5 | `ui_curves` 단계 부재 → `/meta`가 읽는 8개 키 결측 | bootstrap에 추가 |

### 2. 재현성 — 캐시 기반 콜드런이 현행 DB를 재현한다

- [x] `score_meta`의 헤드라인 4값이 현행과 문자열 동일
  → verify: `--fingerprint` 양쪽 비교 → `rank_model`·`rank_features`·
  `rank_train_years`·`rank_test_years` 전부 일치
- [x] 홀드아웃 십분위가 재현된다
  → verify: 콜드런 `precompute` 출력 `1등급 76.9% (73.8-79.7) ... 10등급 28.4%
  (25.4-31.6)` — 문서 인용값과 **신뢰구간까지 소수점 일치**
- [x] 행수 불일치는 **고치지 않고 보고**했다 — 원인이 파이프라인이 아니라
      현행 DB의 낡음이었다
  → 현행 `grid` 21,544 vs `licence ∪ store` 합집합 23,572. `store`(SEMAS)
  적재 후 `build_grid`를 재실행하지 않은 상태였다. 추가되는 2,028 격자는
  인허가 이력이 없어 학습·평가 코호트에 들어가지 않으므로 헤드라인이
  불변이고, 점수 대상만 19,113 → 20,148로 는다. **오너 판단으로 23,572 채택**

**갱신이 필요한 인용 수치** (생존율·AUC·십분위 격차는 불변)

| 항목 | 이전 | 현재 |
|---|---|---|
| 격자 | 21,544 | **23,572** |
| `grid_score` | 229,356행 (12 × 19,113) | **241,776행** (12 × 20,148) |

### 3. 게이트 무회귀

- [x] 콜드 DB에서 `consistency` 17/17 · `test_leakage` PASS ·
      `asof --selftest-cut` PASS
  → verify: `$env:KB_DB='...\kb.db'; cmd /d /c "python -m pipeline.consistency && python -m model.test_leakage && python -m model.asof --selftest-cut"` → exit 0
- [x] `model/asof.py`가 `station_ride`·`grid_place` 부재를 견딘다
  → verify: 두 테이블이 없는 콜드 DB에서 위 게이트 통과. 코드는 이미
  `asof.py:109-116`·`211-221`에서 `try/except` 후 `None` 반환 — 0을 넣지 않는다
- [x] 서비스 테스트 무회귀
  → verify: `python -m pytest service/test_app.py service/test_cost.py -q`
  → exit 0 (`76 passed`)
- [x] 콜드 DB로 실제 서비스가 뜬다 — `/meta`·`/recommend`·`/grid`·`/grids`·
      `/goodwill`·`/estimate`·`/compare` 7종 전부 200
  → verify: 스크래치 프로브 exit 0 (평가격자 20,148 · `/goodwill` 4,559만)

**`pipeline.verify`는 7/8** — `counts`만 실패한다. **파이프라인 결함이 아니다.**
`verify.py:62`의 `c_counts`가 **라이브 API를 호출해** 대조하는데, 캐시 535,603이
현재 원천 535,660보다 57건 뒤처져 있다. 수집을 포함한 진짜 콜드런에서는 통과한다.
캐시 기반 검증의 구조적 한계이므로 README에 명시한다.

### 4. 정리 (파괴적 — 별도 명령)

- [x] `--prune --dry-run`이 삭제 대상 테이블과 회수 용량을 **실행 없이** 보고한다
  → verify: `python -m pipeline.bootstrap --prune --dry-run` → 15개 660,201행
- [x] 죽은 테이블이 실제로 사라졌다 — 단 `--prune`이 아니라 **교체로**
  → 콜드 DB에는 애초에 없으므로, 원본을 콜드 산출물로 갈아끼우면서 함께 빠졌다.
  `kb.db` 460MB / 39테이블 → **359MB / 22테이블**, `PRAGMA quick_check=ok`.
  교체 전 원본은 `kb-pre-coldswap-20260729.db`로 보존(삭제하지 않음)
  - 비정형 기각: `mention` `mention_shop` `trend` `absa_post` `absa_label`
    `gripe_label` `price_label` `uptae_label` `demand_label` `guest_label`
    `merit_label` `text_profile`
  - 실거래가 기각(§12): `realprice` `realprice_done`
  - 소비자 0: `sgis_jipgyegu`
- [ ] `bootstrap`이 위 14개를 **재생성하지 않는다**
  → verify: 콜드 DB의 테이블 목록에 14개가 없음

### 5. 심사위원이 실행 가능

- [ ] `.env.example`에 필요한 키 4종과 발급처가 적혀 있고, 실제 키는 없다
  → verify: `git ls-files .env.example` + 파일에 값 자리 비어 있음 확인
- [ ] `README.md`에 콜드 스타트 절이 있고, **소요 시간과 API 쿼터 한계**를 명시한다
      (서울 일일 900콜 / licence 단독 536콜 / KAKAO 격자 21,544)
  → verify: 해당 절 존재 + 수치가 `pipeline/config.py`와 일치
- [ ] 쿼터 초과 시 중단 지점과 재개 방법이 문서에 있다
  → verify: 문서 확인

## 범위 밖 (건드리지 않음)

- **실제 API 콜드런 실행** — 사용자 결정. 캐시 기반 단계 검증만. `collect` 단계의
  네트워크 호출 자체는 미검증으로 남기고 문서에 명시한다.
- 기각된 실험 스크립트(`model/experiment_*.py`, `absa_*`, `place_exp.py` 등) 삭제 —
  기록이므로 남긴다. bootstrap이 부르지 않을 뿐.
- `station_ride`·`grid_place` **테이블 삭제** — `model/asof.py` 수정이 얽혀 있어
  이번엔 «부재 허용»까지만. 삭제는 별건.
- 모델 하이퍼파라미터·피처셋 변경. LOC2 그대로.
- 벤치마크 가중·영업이익률 재논의 (2026-07-29 결정 확정).
- 데모용 슬림 DB 추출 — 패키징 라운드 별건.

## 제약 (3단계 경계)

- ✅ 항상: 새 모듈 추가, `.env.example`·README 작성, 스크래치 DB 경로에서 실행,
  단계별 게이트 실행, 커밋 전 `ruff check`
- ⚠️ 먼저 확인: 원본 `kb.db`에 대한 `--prune` 실제 실행 · `pipeline/`의 기존 모듈
  시그니처 변경 · `model/asof.py` 수정 · push
- 🛑 절대: 테스트·게이트 약화나 우회 · 재현 실패 시 기대값을 고쳐 통과시키기 ·
  NULL을 0으로 채우기 · 거친 데이터를 격자로 배분 · 목업·폴백 추가 ·
  `kb-baseline-20260728.db` 삭제(유일한 복구 경로) · 실제 API 키를 커밋

- 건드릴 파일: `pipeline/bootstrap.py`(신규) · `model/asof.py`(부재 허용) ·
  `.env.example`(신규) · `README.md` · `.gitignore`(`kb-cold.db`) ·
  `docs/tracking/criteria-coldstart-v1.md`(이 파일)
