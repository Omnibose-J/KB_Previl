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

## (1) 까페 커버리지 — 완료 (2026-07-29)

**원천을 SEMAS 에서 licence_rest 로 바꿨다.** SEMAS 는 21,619곳으로 더 크지만
개·폐업 이력이 없어 «영업 중»의 정의가 화면의 다른 숫자와 어긋난다.
licence_rest 는 같은 인허가 계열이라 좌표계·날짜 처리가 licence 와 동일하다.
그리고 통닭(치킨)은 누락이 아니라 분류 경계 차이로 판명돼 대상에서 뺐다.

- [x] 까페가 licence_rest 커피숍 계열에서 집계 → verify: `pytest service -q`
      `test_cafe_count_comes_from_the_rest_licence_table` · 격자 9610_19460
      에서 42곳(옛 경로 3곳). exit 0
- [x] 까페 외 업태는 원천 불변 → verify:
      `test_other_uptae_still_count_from_the_general_licence_table` ·
      한식·통닭(치킨)·호프/통닭·기타가 competitor_same_uptae 와 일치. exit 0
- [x] 목록(S3)과 상세(S4)가 같은 값 → verify: 추천 상위 3곳 1/5/19곳 일치
- [x] 등급·점수·모델 불변 → verify: grid_score·grid_feature·licence 체크섬
      전후 동일(eefc51c4…/f5eff427…/29edb5f6…) · consistency 17/17
- [x] 회귀 검정 RED→GREEN → verify: REST_UPTAE 를 비우면 `assert 3 == 42`
      로 실패 · 되돌리면 `pytest service -q` 89 passed exit 0

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
