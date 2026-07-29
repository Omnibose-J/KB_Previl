# 수용 기준: 까페 커버리지 → 낡은 수치 갱신 → 격자 변동 알림

작성 2026-07-29 · 마감 2026-08-03 16:00

목표: 카페 창업자가 실제 경쟁 규모를 보고, 문서의 수치가 DB와 일치하며,
자리의 변동을 추적할 수 있다.

## 근거 실측 (2026-07-29, kb.db)

| 업태 | 인허가 영업중 | SEMAS | 배수 | 판정 |
|---|---|---|---|---|
| 까페 | 1,239 | 21,619 | 17.4x | 진짜 누락 (휴게음식점) |
| 통닭(치킨) | 1,630 | 5,206 | 3.2x | 진짜 누락 (테이크아웃) |
| 분식 | 7,519 | 7,618 | 1.0x | 정상 |
| 일식 | 6,962 | 7,085 | 1.0x | 정상 |
| 중국식 | 4,830 | 5,308 | 1.1x | 정상 |
| 한식 | 50,722 | 53,225 | 1.0x | 정상이나 SEMAS [한식]에 횟집·식육이 섞여 1:1 아님 |
| 경양식 | 8,693 | 5,941 | 0.7x | 경계 차이 |
| 호프/통닭 | 8,805 | 2,643 | 0.3x | SEMAS [주점] 분할이 다름 |
| 정종/대포집/소주방 | 1,702 | 12,462 | 7.3x | 〃 |
| 식육(숯불구이) | 1,552 | 8,535 | 5.5x | SEMAS [한식] 내부 분할 |
| 외국음식전문점 | 2,110 | 1,610 | 0.8x | 경계 차이 |

결론: 누락은 까페·통닭(치킨). 나머지는 분류 경계 차이지 누락이 아니므로
전부 SEMAS 로 바꾸면 없던 오차가 새로 들어온다. 1:1 매핑만 쓴다.

## (1) 까페 커버리지

- [ ] 까페 상세의 «현재 영업 중»이 SEMAS 기준 → verify: `/api/grid/{gid}?uptae=까페`
      의 currentStoresHere 가 sameUptaeHere 보다 크고 store 집계와 일치
- [ ] 매핑 없는 업태는 NULL, 화면은 인허가 값으로 → verify: 한식·호프/통닭·
      정종/대포집/소주방·식육(숯불구이)·외국음식전문점·기타 → None
- [ ] 출처가 화면에 표기 → verify: 실제 브라우저 렌더 확인
- [ ] 등급·점수·모델 불변 → verify: grid_score 체크섬 전후 동일 ·
      `python -m pipeline.verify` 8/8 · `python -m pipeline.consistency` 17/17
- [ ] 회귀 검정 RED->GREEN → verify: `python -m pytest service -q` exit 0

## (2) 낡은 수치 문서 갱신

- [ ] 구 격자수 계열 0건 → verify: `git grep -nE "21,?544|229,?356|19,?113|46\.8%"`
      가 model-findings.md·criteria-*.md·findings.md(이력)로만 남음
- [ ] lanes/A-algorithm.md 재학습 후 값 → verify: 75.5/29.2/46.3%p 0건
- [ ] 실행 출력 숫자 정정 → verify: pipeline/bootstrap.py:149 · model/tier2.py:87 = 23,572
- [ ] copy.ts 개업 시작연도 ↔ DB → verify: min(open_y)=1900 대조 (현행 표기 1924)

## (3) 격자 변동 알림

- [ ] 배치가 스냅샷·run 메타를 남김 → verify: 2회 실행 후 score_run 2행
- [ ] 모델 변동과 자리 변동 분리 → verify: model/train_years/rank_features_hash
      가 다른 run 의 등급 델타는 전부 kind='recalibration'
- [ ] 표본 부족·등급경계 왕복은 미발송 → verify: 하한 미달 케이스 단위 검정
- [ ] --asof 로 과거 시점 등급 계산 → verify: `service.precompute --asof 2026-01`
- [ ] 구독 → 이벤트 조회 → verify: POST /api/watch → GET /api/watch/{id}/events 200

## 범위 밖

- 모델·등급·grid_score 재계산. SEMAS 는 이력이 없어 as-of 복원 불가이고
  model/asof.py LEAKY 규약 위반이다. 표시만 보강한다.
- 매핑이 애매한 6업태에 억지 매핑
- 알림 실제 발송(SMTP/푸시) — 이벤트 산출까지
- model-findings.md·criteria-*.md 의 과거 측정값 (그때 잰 기록)
- 새 외부 데이터 수집 (R-ONE·공정위·VWORLD 는 키 미확보)

## 제약

- 항상: 커밋 전 pytest + tsc, 게이트 4종 유지, 단계마다 커밋 분리
- 먼저 확인: kb.db 스키마 변경(레인 A), pipeline/ 수정(공유), push
- 절대: 테스트 약화·정답 하드코딩, 검증 우회, SEMAS 를 모델 피처로 투입,
  NULL 을 0 으로 대체, 매핑 불가 업태에 추정치 삽입
