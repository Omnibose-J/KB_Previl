# 수용 기준: KB 터 기획서 → 백엔드 반영 (외주: Codex)

작성 2026-07-28 · 근거: `KB_터_기획서.docx` · `KB_Previl_개발명세서.md` v1.0 · 실측 프로브(본문 §0-B)
소유: 레인 B(`service/`) + 일부 레인 A(`kb.db` 쓰기 — §W5 이후)
마감: 예선 2026-08-03 16:00 · 실작업 4일(7/28~31, 8/1 패키징·8/2 녹화)

**목표**: 매물 인벤토리 없이, 사용자가 손에 쥔 후보 1~3건을 실질 월 점유비용으로 환산해
「월세 기준 순위 vs 우리 기준 순위」를 뒤집어 보여준다.

---

## 0. 개발명세서 판정 — 무엇을 채택하고 무엇을 버리는가

명세서는 **그린필드 전제**로 쓰였다(신규 `teo/` 트리 · PostgreSQL+PostGIS · SQLAlchemy · Alembic ·
Redis · Prefect). 이 저장소에는 이미 검증된 파이프라인·모델·API가 있고 남은 실작업은 4일이다.
아래 판정 없이 명세서를 그대로 따르면 **이미 통과한 게이트를 전부 다시 세워야 한다.**

### 0-A. 스택 — 명세서 §2 기각

| 명세서 | 판정 | 근거 |
|---|---|---|
| PostgreSQL 16 + PostGIS | **기각** | 공간 연산은 100m 격자(EPSG:5179) + 링 집계로 이미 해결. `grid_score` 229,356행 조회가 인덱스로 즉시 |
| SQLAlchemy 2.0 / Alembic | **기각** | 현행은 raw `sqlite3` 읽기 전용 커넥션. ORM 도입은 순이득 0 |
| Redis / Prefect | **기각** | 요청 경로는 조회+산술뿐. 캐시 대상이 없다 |
| 신규 `teo/` 디렉터리 | **기각** | `pipeline/`·`model/`·`service/` 3레인 경계가 이미 서 있다 |
| Python 3.11 · FastAPI · Pydantic v2 · LightGBM | **채택(이미 사용 중)** | 변경 없음 |

> **2026-07-28 소유자 결정 — 재구조화 승인.** `service/` 재배치, 엔드포인트 교체,
> B→C 계약 변경, `test_app.py` 회귀 가드 강등은 **승인 없이 해도 된다**.
> 위 표의 기각은 *권한*이 아니라 **4일이라는 시간과 아키텍처-실물 일치 요구**에 근거하므로
> 그대로 유지된다. 바꿔 말해 — 기존 코드를 지키느라 우회하지 말고, 대신 스택을 갈아타지도 마라.

> **이 판정을 뒤집으면 안 되는 이유**: `docs/submission.md` §2가 이미
> *"PostgreSQL·크롤러 4-Layer 아키텍처 → 실제 구현: SQLite 단일 DB + FastAPI + React —
> 아키텍처 그림을 실물과 일치시킬 것"*을 기술설명서 교체 항목으로 못박았다.
> 명세서 §2는 그 반증된 그림을 되살린다.

### 0-B. 실측 프로브 결과 — Codex가 가정하면 안 되는 사실

2026-07-28 `kb.db` 직접 조회. **아래는 확인된 값이며 추정이 아니다.**

```
licence 컬럼: mgtno, bplcnm, uptae, addr, open_y, open_m, close_y, close_m,
              state, is_closed, site_area, lon, lat, grid_id, succession_suspect
licence 총계 535,603 · succession_suspect=1 → 32,237
distinct addr 274,028 · 그중 2건 이상 재사용 91,560 (33.4%)
addr에 층 토큰 보유 21.9% (200,000행 표본)
날짜 해상도: 연·월만 (일자 없음)
```

세 가지가 명세서 전제와 다르다:

1. **`flag_succession`이 이미 있다** — `pipeline/normalize.py:140`. 같은 `addr` + 같은 `uptae` +
   폐업 후 90일 내 신규 인허가. 명세서 §5.2.1 레이블의 positive 절반이 이미 구현됨.
   **신규 구축이 아니라 확장이다.**
2. **날짜가 월 단위다** — 명세서 §5.2.1의 `vacancy_days <= 90 / >= 180` 경계를
   일 단위로 계산할 수 없다. 3개월/6개월 근사가 강제되며, 이는 레이블 정의 변경이다.
3. **층이 78% 결측이다** — 명세서 부록 B.4가 *"층을 분리하지 않으면 `addr_tenancy_history`가
   오염되고 M2가 통째로 망가진다 — 파이프라인 전체에서 가장 흔한 실수 지점"*이라 경고한
   조건을 우리 데이터가 만족하지 못한다.

### 0-C. 모델 M1~M4 판정

| | 명세서 | 판정 | 대체 |
|---|---|---|---|
| **M1** 매출 | 상권 평균 × `location_multiplier`로 **매물 단위 분해** (부록 A.2 배수표: 1층 1.00 / 2층 0.55 / 지하 0.45 / 코너 ×1.15) | 🛑 **기각** | 상권×업종 실측값을 **그대로** 쓰고 같은 상권 매물은 동점 처리. 응답에 `revenueResolution: "trade_area"` 명시 |
| **M2** 회수확률 | 승계 프록시 레이블 + LightGBM + isotonic 캘리브레이션 | ✅ **채택(변형)** | 기존 `flag_succession` 확장. 캘리브레이션은 isotonic 대신 **bin별 실측 승계율**(기존 `precompute.py` 패턴) |
| **M3** 적정가 | `listing.premium_asking` 회귀 학습 | ⚠️ **부분 기각** | 매물 0건이라 학습 불가. 기존 `service/goodwill.py` 수익환원 방식 유지. **호가 3분해(§5.3 후반)는 규칙 기반이라 채택** |
| **M4** 문서 판독 | LLM 계약서·등기부 추출 | 🛑 **이번 라운드 제외** | 원문 없음 + 비정형 정밀도 검정 기각 이력(§18·§19). `ltv_ratio` 산수만 선택 항목 |

**M1 기각이 이 문서에서 가장 중요한 판정이다.** 부록 A.2 배수표는 명세서 스스로
*"이 표는 임시값이다"*라고 적었고, 이 저장소는 `CLAUDE.md` 절대규칙 3
(**거친 데이터를 격자로 배분하지 않는다**)과 기록된 공간해상도 결정으로 이를 금지한다.
검증되지 않은 배수를 곱하면 **부담률 전체가 지어낸 숫자**가 되고, 부담률이 랭킹 축이므로
랭킹 전체가 조용히 거짓이 된다.

> 층 효과를 쓰고 싶다면 **매출이 아니라 생존율에는 실측치가 있다**
> (지하 59.8% / 1층 66.2% / 2층 69.9%). 이 구분을 지운 채 층 배수를 매출에 곱하지 말 것.

### 0-D. API 계약 충돌

| 항목 | 명세서 §7.7 | 이 저장소 | 채택 |
|---|---|---|---|
| 금액 단위 | 원(KRW) 정수 | **만원** | **만원 유지** — 프론트 4화면이 이미 만원 포맷. 바꾸면 `test_app.py`+프론트 동시 붕괴 |
| 에러 포맷 | RFC 7807 problem+json | `detail` 문자열(프론트가 문자열로 분기) | **기존 유지** |
| 필드 표기 | snake_case | **camelCase** | **camelCase 유지** |
| 좌표 | — | `[lon, lat]` WGS84 | 유지 |
| 등급 방향 | — | `grade` 1=최상 | 유지 |

명세서 §7 엔드포인트 중 **채택은 §7.3 `/estimate` 하나**다. 명세서 스스로
*"이 엔드포인트가 실사용 가치가 가장 높다 — 사용자는 이미 후보 매물을 손에 쥐고 오기 때문"*이라
적었고, 기획서 §1.4의 핵심 관찰과 정확히 같은 문장이다.
`/search`·`/search/relax`·`/documents/analyze`는 매물 인벤토리·원문이 없어 제외.

---

## 1. 완료 조건

### W1 — `service/cost.py` 실질 월 점유비용 (순수 함수) · 0.5일

- [x] 명세서 §4.1 검증 케이스 3건이 정확히 재현된다 (관리비 0 · `opportunity_rate=0.04` · `horizon_months=36`)

  | 케이스 | 보증금 | 월세 | 권리금 | 회수확률 | 기대 실질비용 |
  |---|---|---|---|---|---|
  | A | 5,000만 | 250만 | 1억 2,000만 | 0.25 | **5,166,667** |
  | B | 3,000만 | 380만 | 2,000만 | 0.60 | **4,122,222** |
  | C | 4,000만 | 310만 | 6,000만 | 0.40 | **4,233,333** |

  → verify: `python -m pytest service/test_cost.py -k "spec_case" -q`
- [x] **순위 역전이 회귀 테스트로 잠긴다** — 월세순 `A<C<B`, 실질비용순 `B<C<A`
  → verify: `python -m pytest service/test_cost.py -k "rank_reversal" -q`
- [x] 경계값: 권리금 0 · 회수확률 0 · 회수확률 1 · 보증금 0에서 예외 없이 정의된 값
  → verify: `python -m pytest service/test_cost.py -k "boundary" -q`
- [x] 파라미터가 하드코딩이 아니라 `CostParams` 기본값이며 요청에서 덮어쓸 수 있다
  → verify: `grep -n "0.04\|36" service/cost.py` — 리터럴이 `CostParams` 정의 안에만 등장
- [x] `service/cost.py`에 `model.*` import도 DB 접근도 없다 (순수 함수)
  → verify: `grep -nE "^(from|import) (model|sqlite3)" service/cost.py` → 0건

**W1 실행 증거 (2026-07-28)**

- `python -m pytest service/test_cost.py -k "spec_case" -q` → exit 0 (`3 passed, 7 deselected`)
- `python -m pytest service/test_cost.py -k "rank_reversal" -q` → exit 0 (`1 passed, 9 deselected`)
- `python -m pytest service/test_cost.py -k "boundary" -q` → exit 0 (`5 passed, 5 deselected`)
- `$env:Path='C:\Program Files\Git\usr\bin;'+$env:Path; grep -n "0.04\|36" service/cost.py` → exit 0 (리터럴은 `CostParams` 정의 2건)
- `$env:Path='C:\Program Files\Git\usr\bin;'+$env:Path; grep -nE "^(from|import) (model|sqlite3)" service/cost.py` → exit 1 (일치 0건)

### W2 — `POST /estimate` 단일 후보 계산 · 0.5일

- [x] 주소 대신 **좌표 또는 grid_id + 업태 + 보증금/월세/권리금/면적/층**을 받아 단일 결과를 낸다
  → verify: `python -m pytest service/test_app.py -k "estimate" -q`
- [x] 평가 대상 밖 격자는 **404 + `"이웃 이력 부족으로 평가하지 않음"`** 으로 시작하는 detail
  (기존 계약 그대로, 프론트가 이 문자열로 분기)
  → verify: `python -m pytest service/test_app.py -k "estimate_not_evaluated" -q`
- [x] 상권 밖 격자(매출 NULL)는 **실질비용은 내고 부담률은 `null`** + `missingAxes`에 명시.
      0으로 채우지 않는다
  → verify: `python -m pytest service/test_app.py -k "estimate_outside_trade_area" -q`

**W2 실행 증거 (2026-07-28)**

- `python -m pytest service/test_app.py -k "estimate" -q` → exit 0 (`4 passed, 51 deselected`)
- `python -m pytest service/test_app.py -k "estimate_not_evaluated" -q` → exit 0 (`1 passed, 54 deselected`)
- `python -m pytest service/test_app.py -k "estimate_outside_trade_area" -q` → exit 0 (`1 passed, 54 deselected`)

### W3 — `POST /compare` 후보 1~3건 병렬 순위 · 0.5일

- [x] 응답이 `rentRank`와 `teoRank`를 **둘 다** 싣는다 (명세서 §6.1 — 하나라도 빠지면 실패)
  → verify: `python -m pytest service/test_app.py -k "compare_returns_both_ranks" -q`
- [x] 동률 tie-break가 `burdenRate → effectiveCost → recoveryProb` 순으로 결정적이다
  → verify: `python -m pytest service/test_app.py -k "compare_tiebreak" -q`
- [x] **부담률은 상권이 다른 후보 간에만 비교 가능**하다는 사실이 응답에 실린다 —
      같은 상권 후보끼리는 `revenueTied: true`
  → verify: `python -m pytest service/test_app.py -k "compare_same_trade_area_ties" -q`

**W3 실행 증거 (2026-07-28)**

- `python -m pytest service/test_app.py -k "compare_returns_both_ranks" -q` → exit 0 (`1 passed, 54 deselected`)
- `python -m pytest service/test_app.py -k "compare_tiebreak" -q` → exit 0 (`1 passed, 54 deselected`)
- `python -m pytest service/test_app.py -k "compare_same_trade_area_ties" -q` → exit 0 (`1 passed, 54 deselected`)

### W4 — 호가 3분해 (기존 `goodwill.py` 확장) · 0.5일

- [x] 기존 무형/유형 축을 **시설 / 영업 / 바닥(잔차)** 으로 리라벨해 함께 낸다
      (시설 ← `tangible`, 영업 ← `intangible`, 바닥 ← `asking − 시설 − 영업`)
  → verify: `python -m pytest service/test_app.py -k "goodwill_decomposition" -q`
- [x] 바닥권리금이 **음수면 음수 그대로** 낸다 (0으로 깎지 않는다 — 호가가 산정근거보다 낮다는 사실)
  → verify: `python -m pytest service/test_app.py -k "floor_key_negative" -q`
- [x] 벤치마크 레벨 표기(`benchmarkLevel: 4` + 경고 문구)가 유지된다
  → verify: `python -m pytest service/test_app.py -k "goodwill_slim_input" -q` (기존 테스트 무회귀)

**W4 실행 증거 (2026-07-28)**

- `python -m pytest service/test_app.py -k "goodwill_decomposition" -q` → exit 0 (`1 passed, 54 deselected`)
- `python -m pytest service/test_app.py -k "floor_key_negative" -q` → exit 0 (`1 passed, 54 deselected`)
- `python -m pytest service/test_app.py -k "goodwill_slim_input" -q` → exit 0 (`1 passed, 54 deselected`)

**W1~W4 = 2일. 여기까지가 예선 확정분이며, 이 넷만으로 기획서의 데모 두 장(순위 역전·호가 분해)이 선다.**

### W5 — 승계 체인 + 레이블 확장 (레인 A · `kb.db` 쓰기) · 1일 · **도전 과제**

- [ ] `addr_tenancy` 테이블 생성 — 주소별 `seq`·`tenure_months`·`vacancy_months_after`·`succeeded`
  → verify: `python -m pipeline.addr_history --selftest`
- [ ] 레이블 경계가 **월 단위 근사임이 코드 주석과 산출 메타에 명시**된다
      (`<=3개월`=True / `>=6개월`=False / 4~5개월=제외 / 후속 없음=False)
  → verify: `grep -n "월 단위" pipeline/addr_history.py`
- [ ] **층 결측 영향을 측정한다** — 층 토큰 보유 21.9% 부분집합에서 층 분리 유무에 따른
      승계율 차이를 리포트. 차이가 크면 층 미상 건의 처리 방침을 기록
  → verify: `python -m pipeline.addr_history --floor-impact`
- [ ] 기존 `flag_succession`(32,237건)과의 차이 건수가 리포트된다 (중복 구현 방지)
  → verify: `python -m pipeline.addr_history --diff-legacy`

### W6 — M2 학습 + 캘리브레이션 · 1일 · **도전 과제**

- [ ] **시간 기반 분할** (랜덤 분할 금지 — 명세서 §5.2.2 + 이 저장소 규율 동일)
  → verify: `python -m model.recovery --holdout`
- [ ] 확률을 원값으로 쓰지 않고 **bin별 실측 승계율**로 캘리브레이션한다
      (기존 `precompute.py` 등급 패턴과 동일)
  → verify: `python -m model.recovery --calibration`
- [ ] 누수 가드 통과
  → verify: `python -m model.test_leakage`
- [ ] **개선이 없으면 없다고 기록한다.** 기여 판별 불가 시 `docs/model-findings.md`에
      negative result로 남기고 회수확률은 W7의 상수/생존곡선 프록시로 되돌린다
  → verify: `docs/model-findings.md`에 실험 대장 항목 추가 확인

### W7 — 회수확률 배선 · 0.5일

- [ ] `/estimate`·`/compare`의 회수확률 출처가 **상수 → 생존곡선 프록시 → M2** 순으로
      교체 가능하며, 응답이 어느 것을 썼는지 `recoverySource`로 밝힌다
  → verify: `python -m pytest service/test_app.py -k "recovery_source" -q`
- [ ] **"회수확률"이 아니라 "승계 확률"로 라벨링된다** — 명세서 §5.2의
      `P(승계) × E[지불비율]` 중 우리는 **앞항만** 낸다. 지불비율 원천(부동산원 앵커)은 미확보
  → verify: `grep -rn "recoveryProb\|승계" service/app.py` — 응답 필드 설명에 명시 확인

### 전 구간 무회귀

- [x] 기존 게이트 4종이 전부 통과 상태를 유지한다
  → verify: `python -m pipeline.verify && python -m pipeline.consistency && python -m model.test_leakage && python -m model.asof --selftest-cut`
- [x] 기존 API 테스트 40여 건 무회귀
  → verify: `python -m pytest service/test_app.py -q`
- [x] 요청 경로에 모델이 새지 않았다
  → verify: `grep -rn "^from model\|^import model" service/*.py` → `precompute.py` 외 0건
- [x] 트립와이어 유지
  → verify: `grep -rn "trend\|mention" service/*.py` → 0건

**전 구간 실행 증거 (2026-07-28)**

- PowerShell 5.1이 `&&`를 파싱하지 못해
  `$env:PYTHONUTF8=1; $env:PYTHONIOENCODING='utf-8'; cmd /d /c "python -m pipeline.verify && python -m pipeline.consistency && python -m model.test_leakage && python -m model.asof --selftest-cut"`
  로 같은 fail-fast 체인을 실행 → exit 0 (`8/8`, `17/17`, 누수 가드 PASS, `≤T` 불변성 PASS)
- 위 게이트는 `pipeline.db.init()`의 숨은 schema commit 때문에 공유 DB를 변경했다.
  기능 게이트 결과는 유효하지만 읽기 전용 증거로는 무효다. 원인과 영향은
  `docs/tracking/findings.md` F-A2에 기록했다
- `python -m pytest service/test_app.py -q` → exit 0 (`55 passed`)
- `$env:Path='C:\Program Files\Git\usr\bin;'+$env:Path; grep -rn "^from model\|^import model" service/*.py`
  → exit 0 (`service/precompute.py`만 일치)
- `$env:Path='C:\Program Files\Git\usr\bin;'+$env:Path; grep -rn "trend\|mention" service/*.py`
  → exit 1 (일치 0건)
- `python -m pytest service/test_cost.py service/test_app.py -q -p no:cacheprovider`
  → exit 0 (`65 passed`)
- `ruff check service` → exit 0

---

## 2. 범위 밖 (건드리지 않음)

- **매물 인벤토리 테이블** (`listing`) — 실데이터 0건. 빈 스키마만 만들면 목업 유혹이 생긴다
- **법원경매 수집** (S9) — 별도 판정: 권리금 0건 + 매물 아님 + 시점 과거. **본선 카드**
- **M1 매출 분해 · 부록 A.2 배수표** — §0-C 기각
- **M3 호가 회귀 학습** — 학습 데이터 0건 (분해는 W4에서 규칙 기반으로 함)
- **M4 계약서·등기부 LLM 판독** — 원문 없음
- **조건 완화** (§6.2) — 매물 수를 셀 수 없어 "몇 건" 칸이 안 채워짐
- **PostgreSQL·PostGIS·ORM·Redis 이관** — §0-A
- `probe/` (읽기 전용) · `docs/기획안*.md`·`docs/주제 선정*.md` (제안 시점 기록, 보존)
- 프론트 컴포넌트 — 레인 C. 이 문서는 API 계약까지만

---

## 3. 제약 (3단계 경계)

**✅ 항상 (확인 없이 해도 됨)**
- `service/` 안에서 새 모듈 추가 · 테스트 추가 · 기존 테스트를 **깨지 않는** 리팩터
- 커밋 전 게이트 4종 + `pytest service/` 실행
- 파라미터는 전부 `CostParams` 등 설정 객체로 (명세서 부록 A: *"전부 설정 파일로 빼고 하드코딩하지 마라"*)

**⚠️ 먼저 확인 (사람 승인 필요)**
- `kb.db` **쓰기** — W5 이후는 레인 A 영역이다 (`CLAUDE.md`: B·C는 읽기만)
- `grid_score`·`score_meta` 스키마 변경 — 레인 B·C 동시 파급
- 신규 의존성 추가 · `model/train.py`의 세 상수 변경(→ precompute 전량 재계산)
- push

> `service/` 재구조화와 B→C 계약 변경은 **2026-07-28 승인 완료**(§0-A) — 확인 불요.
> 다만 계약을 바꾸면 `frontend/app/src/api/types.ts`와 화면 4종이 함께 깨지므로,
> 바꾼 필드를 `lanes/B-backend.md`에 **같은 커밋에서** 갱신해 레인 C가 따라올 수 있게 한다.

**🛑 절대**
- 테스트·스펙 수정/약화, 테스트 입력 정답 하드코딩, special-case, 검증 우회
- **NULL을 0으로 채우기** — 상권 밖 격자 46.8%. 0을 넣으면 "최악의 입지"로 랭크된다
- **거친 데이터를 매물·격자 단위로 배분하기** — M1 배수표가 정확히 이것
- **모델 원확률 노출** — 등급과 실측치만
- 요청 경로에서 모델 적합 / `service/`에 `model.*` import (`precompute.py` 제외)
- **목업·폴백** — 원천이 없으면 합성하지 말고 503/404/422로 실패한다
- `trend`·`mention`·`mention_shop` 테이블을 어떤 형태로도 서빙에 노출
- "상위 n%" 표기 (→ "n등급 · 실측 n%") · "유망/뜨는/전망" 류 표현
- 상용 부동산 플랫폼 크롤링 (2026.1 판례)
- **추정치를 단정적으로 표기** — 구간 + 면책 문구 필수

**건드릴 파일**
```
신규:  service/cost.py · service/test_cost.py
       pipeline/addr_history.py (W5~) · model/recovery.py (W6~)
수정:  service/app.py (라우트 2종 추가) · service/api.py (조회 보조)
       service/goodwill.py (3분해 리라벨) · service/test_app.py (케이스 추가)
문서:  docs/serving-design.md (§8 상태 갱신) · lanes/B-backend.md (계약 추가)
       docs/model-findings.md (W6 결과 — 성공이든 실패든)
```

---

## 4. 진행 순서와 중단 지점

명세서 §8의 원칙을 채택한다 — *"3번(cost.py)을 4·5번(모델)보다 먼저 해라.
모델이 없어도 회수확률을 상수(0.4)로 넣으면 계산기와 데모가 돌아간다."*

```
W1 → W2 → W3 → W4      2일   예선 확정분. 여기서 멈춰도 데모 두 장이 선다
W5 → W6 → W7           2일   도전 과제. 실패해도 W1~W4가 안 깨진다
```

**W6가 실패하는 것은 정상 종료다.** 이 저장소는 기여를 판별할 수 없는 신호를
아홉 번 기각하고 그것을 서사로 삼았다. 회수확률도 같은 규율을 받는다 —
승계 레이블이 신호를 못 내면 `docs/model-findings.md`에 negative result로 남기고
회수확률은 등급별 실측 생존곡선 프록시로 되돌린 뒤, **"확률이 아니라 하한"**으로 라벨링한다.

---

## 5. Codex 인수인계 시 함께 읽힐 것

| 파일 | 왜 |
|---|---|
| `CLAUDE.md` | 절대규칙 6종 — 전부 실제 사고가 났던 지점 |
| `docs/serving-design.md` | 모델↔백엔드 경계, §5 "절대 하면 안 되는 것" 9종 |
| `lanes/B-backend.md` | B→C HTTP 계약 전문 |
| `service/test_app.py` | 회귀 가드 40여 건 — 무엇이 계약인지가 여기 있다 |
| 이 문서 §0 | 개발명세서를 그대로 따르면 안 되는 이유 |
