# 수용 기준: R-ONE 참고 데이터 3종 통합 (표기 전용)

목표: 부동산원 R-ONE 통계 3종(권리금 앵커 · 층별 효용비율 · 상권 임대료/공실률)을
자리 리포트에 **참고 표기**로 붙여, 사용자가 자기 숫자를 시장 기준선과 대볼 수 있게 한다.
점수·등급·추천 순위는 변하지 않는다.

## 완료 조건

**실행 증거 (2026-08-03, `PYTHONUTF8=1 PYTHONIOENCODING=utf-8`, `KB_DB=kb.db`)**
게이트를 UTF-8 없이 돌리면 `crosssource` 가 상관 r=0.828 로 통과한 **뒤** em dash 출력에서
`cp949` 인코딩 오류로 FAIL 로 뒤집힌다. 데이터 실패와 구분이 안 되므로 항상 붙여 돌린다.

### W1 — 수집·적재

- [x] `pipeline/rone.py` 가 R-ONE 4개 통계표에서 서울 관련 행만 뽑아 `rone_ref` 에 적재한다
  → verify: `python -m pipeline.rone` → **exit 0** (`rone_ref` 540행 · goodwill 48 / floor_ratio 364 / rent 64 / vacancy 64)
- [x] 상권 59개의 임대료 분포가 적재되고, 서울 평균이 그 분포 안에 든다
  → verify: `python -m pipeline.rone --verify` → **exit 0** (상권 59 ≥ 50 · 서울 52.78 ∈ [24.4, 152.2])

**설계 정정 (2026-08-03, 구현 중)**: 상권 중심 좌표 지오코딩을 시도했으나 카카오 키워드
1순위가 랜드마크로 잡혀 상권 중심에서 최대 3km 어긋났다(동대문→홍릉시험림, 종로→경복궁).
부동산원 상권 경계를 알 근거가 없어 좌표를 창작하지 않는다. **격자↔상권 매칭을 폐기**하고,
사용자가 입력한 임대료를 59개 상권 분포에 대보는 백분위 표기로 교체한다 — 매칭 근거가
필요 없고 답하는 질문은 같다. 59개는 부동산원이 고른 **주요 상권**이라 서울 대표 표본이
아니므로 "주요 상권 대비"로 표기한다.
- [x] 테이블이 없어도 서버가 기동하고 파이프라인 게이트가 그대로 통과한다
  → verify: `python -m pipeline.verify` → **7/8** (`counts` 는 캐시 재구축 DB 의 기존 실패, README 기재) ·
        `python -m pipeline.consistency` → **18/18 PASS**

### W2 — 누수 차단 (이 작업의 핵심 위험)

- [x] `rone_ref` 가 점수 계보 어디에도 들어가지 않는다
  → verify: `python -m pipeline.consistency roneisolation` → **PASS**
        (순위 경로 66개 파일에서 `rone_` 참조 0건 — `model/*.py` · `service/precompute.py` · `pipeline/features.py`)
- [x] 모델 재학습 없이 붙는다 — `grid_score` 행수 불변
  → verify: `SELECT COUNT(*) FROM grid_score` → **241,776** (작업 전후 동일) ·
        `python -m model.test_leakage` → **exit 0, 누수 가드 PASS**

### W3 — 서빙 (레인 B)

- [x] `/api/goodwill` 응답에 `marketAnchor` 가 붙고, 있어도 추정가 산식이 그대로다
  → verify: `python -m pytest service/ -k "market_anchor" -q` → **PASS**
- [x] `/api/estimate` 응답에 `floorReference` 가 붙고, 층이 달라도 `effectiveCost` 는 같다
  → verify: `python -m pytest service/ -k "floor_reference" -q` → **PASS** (3층은 원천에 없어 `null`)
- [x] `/api/estimate` 응답에 `marketRent` 가 붙고, 비싼 임대료일수록 백분위가 높다
  → verify: `python -m pytest service/ -k "market_rent" -q` → **PASS**
- [x] 임대료가 0 이면 `percentile` 이 `null` 이고 기준선만 남는다 (0 으로 채우지 않는다)
  → verify: `python -m pytest service/ -k "market_rent_no_percentile" -q` → **PASS**
- [x] **테이블 부재 시 200 + 해당 필드 `null`** — 합성값·폴백 없음
  → verify: `python -m pytest service/ -k "rone_absent" -q` → **PASS**
- [x] 기존 서빙 계약이 하나도 깨지지 않는다
  → verify: `python -m pytest service/ -q` → **158 passed, 0 failed** (기준선 153 + 신규 5)

### W4 — 화면 (레인 C)

- [x] `marketAnchor` 가 GoodwillCard 에, `floorReference`·`marketRent` 가 OccupancyCostCard 에 표기된다
  → verify: `npx tsc --noEmit` → **exit 0** · `npm run build` → **exit 0 (built in 7.12s)**
- [x] 필드가 `null` 이면 해당 줄이 렌더되지 않는다 (빈 껍데기·"-" 금지)
  → verify: 실제 빌드본을 FastAPI 가 서빙하는 상태에서 Playwright 육안 확인 —
        층 3층 → 층 줄 사라짐 · 월 임대료 0 → 백분위 문장 사라지고 기준선만 남음
- [x] 모든 표기에 단위·기간·출처가 동반된다
  → verify: 렌더 텍스트 «넣으신 임대료는 ㎡당 5.6만원이에요. … 59곳과 견주면 32곳보다 비싼 편이에요 /
        서울 소규모 상가 평균은 ㎡당 5.3만원, 빈 가게는 6.4%예요 / 지하1층은 서울에서 1층 임대료의 38% 수준이에요 /
        2026년 2분기 · 한국부동산원 · 이 자리의 점수와 등급에는 쓰이지 않아요»

### W5 — 제출물

- [x] `service/demo_db.py` 의 `TABLES` 에 `rone_ref` 가 추가되고 감사가 통과한다
  → verify: `python -m service.demo_db --audit` → **exit 0** (선언 17 = 코드 참조 17, 누락·잉여·부재 0)
- [x] `.env.example` 에 `RONE_API_KEY` 가 있고, 없어도 콜드스타트가 완주한다
  → verify: 선택 단계라 `pipeline.bootstrap` 18단계가 불변 — 키가 없으면 `rone_ref` 가 비고 서빙이 `null` 을 낸다
- [ ] **보류 — 소유자 지시(2026-08-03): 수정사항이 더 남아 제출물은 갱신하지 않는다.**
      서비스가 굳으면 아래 둘을 한 번 돌리면 반영된다.
  → `python -m service.demo_db --out kb-demo.db` · `python build.py --rehearse`

### W6 — 문서 정정

- [x] `api-applications.md`·`data-inventory.md` 의 "R-ONE 키 없음" 기술이 실제 상태와 맞는다
  → verify: 두 문서에서 R-ONE 절을 «확보 완료»로 교체하고, 호출 규약(필수 인자 2개·기간 인자 금지·
        지역축이 표마다 갈림)과 매칭 폐기 사유를 남겼다. 남은 미확보는 상권 구획도(`15086933`)로 이동
- [x] `README.md`·`기술설명서-작성자료.md` 미확보 원천 목록이 정정된다
  → verify: R-ONE 을 «확보했으나 표기 전용»으로 옮기고, **자치구 단위 권리금은 원천 자체가 시도
        단위라 존재하지 않는다**는 사실을 남겼다 (신청하면 생기는 것이 아니다)

## 범위 밖 (건드리지 않음)

- 모델 재학습 · 피처 추가 · `grid_score` 재채점 — R-ONE 은 예측에 안 쓴다
- 층 보정을 실질 점유비용 **계산식**에 넣는 것 (F-A5: 층으로 보이던 것은 면적이었다)
- 상권 폴리곤 확보(data.go.kr 15086933) 및 격자↔상권 경계 매칭
- 자치구 단위 권리금 — R-ONE 에 존재하지 않는다 (시도 단위가 최선)
- `pipeline.bootstrap` 18단계 계약 변경 — R-ONE 은 선택 단계
- 옛 계보 STATBL_ID(`A_2024_*`) 시계열 연결 — 최신 스냅샷만 쓴다
- 권리금 앵커를 승계확률에 곱하는 것 (`P(승계) × E[지불비율]` 은 여전히 앞항만)

## 제약

- ✅ 항상: 커밋 전 `pytest service/` · 레인 소유권 준수(`pipeline/` 은 공유라 변경 최소) · 카피는 해요체·고객 주어
- ⚠️ 먼저 확인: `kb.db` 스키마 추가(레인 A 소유) · `demo_db.TABLES` 변경 · 커밋/푸시
- 🛑 절대: 테스트 수정·약화 · 기대값 하드코딩 · 검증 우회 · **R-ONE 값을 점수/등급/순위에 투입** ·
  **경계 주장 없이 "이 자리는 X 상권" 표기** · 결측을 0 이나 서울 평균으로 채우기

건드린 파일 (실제):
`pipeline/rone.py`(신규) · `service/rone.py`(신규) · `pipeline/db.py` · `pipeline/consistency.py` ·
`service/{goodwill,estimation,schemas,demo_db,test_app}.py` ·
`frontend/app/src/api/types.ts` · `frontend/app/src/lib/format.ts` ·
`frontend/app/src/components/{GoodwillCard,OccupancyCostCard}.{tsx,module.css}` · `.env.example` ·
`README.md` · `docs/{api-applications,data-inventory,기술설명서-작성자료}.md`

`rone_area`(상권 좌표)는 만들지 않았다 — 매칭을 폐기하면서 필요가 없어졌다.
