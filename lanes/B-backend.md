# 레인 B — 백엔드

**소유**: `service/` (단 `service/precompute.py`는 레인 A 소유)
**읽기만**: `pipeline/`, `model/`, `kb.db`
**쓰기 금지**: `kb.db` — 레인 A만 쓴다

---

## 지금 있는 것

`service/api.py` — 조회 함수 초안. **스펙 미확정이라 형태는 확정 아님.**

- `meta()` — 업태·자치구 목록, 등급별 실측 생존율, 모델 성능·한계
- `recommend(uptae, district, top, require_sales, min_grade)`
- `grid_detail(grid_id, uptae)` / `at_point(lon, lat, uptae)`
- `district_summary(uptae)` — 자치구별 상위등급 비율

HTTP 계층은 **협의 문서 나온 뒤** 작성한다. FastAPI 0.115.6 설치돼 있음.

## 데이터 원천

`grid_score` **229,356행** (12업태 × 19,113격자). 레인 A가 생성. 조회는 인덱스 타므로 즉시.

```sql
grid_score(uptae, grid_id, score, grade, observed)   -- grade 1 = 상위 10%
score_meta(k, v)                                     -- as_of, observed_by_grade, overall_survival
```

조인 대상: `grid_feature`(격자 피처) · `grid_sgis`(행정동명) · `grid_access`(지하철)

## 응답에 반드시 지켜야 할 것

1. **`observed`를 쓰고 `score`를 노출하지 않는다.** 모델 확률은 2.7~6.7%p 낙관 편향이라, 등급에서 실제로 관측된 생존율을 보여준다.
2. **NULL은 NULL로.** 매출 없는 격자(46.8%)를 0으로 내보내면 UI가 "최악의 입지"로 그린다. `available: false` 같은 플래그로 구분.
3. **출처 해상도를 함께 준다.** 생활인구·사업체는 행정동, 매출·유동인구는 상권(반경 ~151m), 경쟁·이력은 격자. `api.RESOLUTION` 참고.
4. **한계 문구를 meta에 싣는다.** 상위 10%도 27% 폐업 · AUC 0.59는 무작위보다 나은 수준.

## 손익 계산

`model.economics.scenario(매출, 마진, 초기투자, 임대료, 생존곡선)` 호출.

- **임대료는 사용자 입력.** 공개 데이터는 전국 368개 권역이라 매물 단위로 못 쓴다
- **마진은 임대료 차감 전 값(기본 0.25).** 공표 영업이익률(10~15%)을 그대로 넣으면 임대료 이중 차감

## 환경

DB 경로는 `pipeline.config.DB_PATH`. 환경변수 `KB_DB`로 덮어쓸 수 있다(worktree 대응). 키는 `pipeline.config.load_env()`로 읽는다 — 직접 파싱하지 말 것.

## 레인 C와의 계약

**미확정.** 스펙 협의 후 여기에 엔드포인트·응답 스키마를 기록한다. 그 전까지 C는 `docs/ui-data-contract.md`를 본다.
