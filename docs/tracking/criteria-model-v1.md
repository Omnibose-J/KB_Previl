# 수용 기준: 생존예측 모델 v1 — 검증 프레임 우선

작성 2026-07-26 · 선행: `criteria-pipeline-v1.md` (완료) · 순서 원칙: **평가 하니스가 모델보다 먼저 존재한다**

목표: "이 자리에 이 업종으로 열면 3년 뒤 살아남을 확률"을 과거 데이터로 학습하고, **시간 분리된 홀드아웃에서 베이스라인 대비 개선을 실제로 증명**한다. 개선이 없으면 없다고 보고한다.

---

## 1단계 — as-of 피처 (누수 차단이 전부)

- [ ] 시점 T의 격자 상태를 인허가 이력만으로 재구성하는 함수가 있고, **T 이후 정보를 한 건도 참조하지 않는다** → verify: `python -m model.asof --selftest` — 동일 격자를 T=2015/2019/2023으로 뽑았을 때 값이 서로 다르고, 각 값이 "개업일≤T이고 (폐업일>T 또는 미폐업)" 집계와 정확히 일치, exit 0
- [ ] **누수 탐지 테스트가 RED→GREEN으로 통과한다** → verify: `python -m model.test_leakage` — 일부러 T 이후 폐업정보를 넣은 피처셋이 AUC 급등으로 탐지되는지 확인(RED), 정상 피처셋은 탐지되지 않음(GREEN), exit 0
- [ ] 피처 목록과 각 피처의 "관측 가능 시점"이 명시적으로 문서화된다 → verify: `python -m model.asof --describe` 가 피처별 as-of 근거를 출력

## 2단계 — 라벨

- [ ] 개업 코호트 → N년 생존 라벨이 `cohort.py`와 **동일한 정의**로 생성된다 (분모=관측 가능분) → verify: `python -m model.dataset --year 2019 --horizon 3 --check` — 라벨 평균 생존율이 `cohort_survival` 2019년 3년 값과 ±0.5%p 이내
- [ ] 우편절단된 행이 데이터셋에서 제외된다 → verify: 위 명령이 `excluded_censored` 건수를 출력하고, 포함된 행은 전부 T+3년이 경과

## 3단계 — 평가 하니스 (모델보다 먼저 완성)

- [ ] **시간 분리** train/test가 강제된다 — 학습 연도 < 검증 연도, 겹침 0 → verify: `python -m model.evaluate --dry` 가 train/test 연도와 교집합 0을 출력
- [ ] **베이스라인 3종**이 구현되고 점수가 나온다: ①전체 평균 생존율 ②업태별 평균 ③격자 과거 생존율 단순 사용 → verify: `python -m model.evaluate --baselines-only` — 3종 AUC/Brier 출력, exit 0
- [ ] 지표가 AUC 단독이 아니라 **Brier score(보정)와 lift@decile**를 함께 낸다 → verify: 위 출력에 3개 지표 모두 존재
- [ ] 하니스가 **모델 없이도 동작**한다 (모델은 나중에 꽂는다) → verify: `--baselines-only`가 모델 코드 없이 exit 0

## 4단계 — 모델

- [ ] 로지스틱 회귀가 학습되고 **계수(=가중치)가 해석 가능하게 출력**된다 → verify: `python -m model.train --model logit` — 피처별 계수·부호·표준화 기여도 출력
- [ ] GBM이 학습되고 로지스틱과 **같은 하니스로 비교**된다 → verify: `python -m model.evaluate --models logit,gbm` — 동일 split, 동일 지표로 나란히 출력
- [ ] **홀드아웃에서 최소 하나의 모델이 베이스라인을 이긴다** — AUC 기준 최소 +0.02 → verify: `python -m model.evaluate --assert-beats-baseline` exit 0
  - **이기지 못하면 그대로 보고한다.** 임계를 낮추거나 split을 바꿔 통과시키는 것은 금지(🛑).
- [ ] 계수 부호가 상식과 충돌하면 **숨기지 않고 기록**한다 (예: 경쟁이 많을수록 생존↑) → verify: `docs/model-findings.md`에 부호별 해석과 반례 검토 기록

## 5단계 — 기존 자산 무결성

- [ ] 기존 검증이 그대로 통과한다 → verify: `python -m pipeline.verify` 8/8 · `python -m pipeline.consistency` 17/17
- [ ] `kb.db` 기존 테이블 스키마가 변경되지 않는다 (모델 산출물은 신규 테이블에만) → verify: `sqlite3 kb.db ".schema grid_feature"` 가 이전과 동일

---

## 범위 밖 (건드리지 않음)
- 딥러닝 — 표본 규모(연간 개업 1.2만, 피처 십수 개)에서 GBM 대비 이점이 없다. **요청 시에만** 착수하며, 그때도 GBM을 이기는지부터 확인
- 생활인구·상권매출 피처 — 과거 값이 없어(각각 현재만/2021년~) as-of 재구성 불가. **1차 모델에서 제외**하고, 현재 시점 추천에만 별도로 더하되 "미검증"으로 표기
- 추천 UI·순위 표출
- 비정형(블로그·리뷰) 결합
- 하이퍼파라미터 튜닝 대회 — 베이스라인 대비 개선 여부가 관심사이지 소수점 경쟁이 아니다
- 인과 해석 — 계수는 상관이지 "이렇게 하면 생존한다"가 아니다. 문구로 못 박는다

## 제약 (3단계 경계)
- ✅ **항상**: as-of 함수만으로 피처 생성 · 새 지표 추가 시 베이스라인도 함께 재계산 · 결과를 `docs/model-findings.md`에 누적 기록
- ⚠️ **먼저 확인**: 새 의존성(scikit-learn/lightgbm) 설치 · `kb.db` 스키마 변경 · 딥러닝 착수 · 학습/검증 연도 구성 변경
- 🛑 **절대**:
  - 개업 시점 **이후** 정보를 피처에 사용 (현재 점포수, 현재 생존율, 최신 매출)
  - test 연도 데이터로 피처 스케일링·선택·튜닝 (fit은 train에서만)
  - 베이스라인을 약화시키거나 빼서 모델을 이기게 만들기
  - 성능이 안 나올 때 split·임계·지표를 바꿔 통과시키기
  - 코호트/생존율 정의를 모델 쪽에서 재정의 (`cohort.py`와 단일 정의 유지)
  - 검증 실패를 "튜닝 부족"으로 서술하며 넘어가기 — **실패는 실패로 보고**
- **건드릴 파일**: 신규 `model/` (asof.py, dataset.py, evaluate.py, train.py, test_leakage.py) · 신규 `docs/model-findings.md` · `kb.db` 신규 테이블만 · **`pipeline/` 읽기 전용**
