# `service/api.py` 를 같은 이름의 패키지로 바꾼다

**Decision:** 2026-08-01. `service/api.py`(1,165줄)를 삭제하고 `service/api/`
패키지로 대체한다. 하위 모듈은 `base` · `context` · `cells` · `meta` ·
`search` · `changes` 여섯 개이고, `__init__.py` 가 기존 공개 이름을 그대로
재수출한다. **import 경로(`from service import api`, `api.recommend(...)`)는
바뀌지 않는다.**

**Context:** 한 파일에 7개 도메인(도시 메타·격자 상세·추천·주변 가게·방문객
동반자·매출 구성·변동 이력)이 섞여 있었다. `api.<이름>` 참조가 저장소 전체에
21종 · 여러 파일에 흩어져 있고, 서빙 계약 시험 121종이 이 모듈에 의존한다.

**Why:**
- 같은 이름의 패키지로 만들면 **호출부를 한 줄도 고치지 않는다.** 마감 직전에
  바꾸는 파일 수가 곧 위험이므로, 분해의 이득만 취하고 파급은 0 으로 둔다.
- 계층이 단방향으로 정리됐다 — `base`·`context` 는 의존이 없고, `cells` →
  `base`, `meta` → `base`·`cells`, `search`·`changes` 가 그 위다. 순환 없음을
  분해 전에 그래프로 확인하고 진행했다.
- 남은 파일이 전부 400줄 이하다(최대 `context` 328줄).

**Rejected:**
- *`service/query/` 새 패키지 + `api.py` 를 얇은 재수출 파일로* — 파일이 하나
  더 늘고 «api 와 query 중 어디를 보나» 라는 질문이 생긴다. 패키지 `__init__`
  이 이미 그 역할을 한다.
- *분해하지 않고 둔다* — 1,165줄에 7개 도메인은 읽는 사람이 전체를 훑어야
  한 가지를 안다. 소유자 조건에 정면으로 걸린다.
- *하위 모듈을 9개로* — 처음 잡았던 안이다. `errors` 23줄 · `party` 66줄처럼
  조각이 생겨 과분할이었다. 6개로 합쳤다.

**부수 발견:** 이름을 직접 import 하면 monkeypatch 이음매가 끊긴다.
`readonly_connection` 을 `from .base import` 로 가져오면 테스트가
`api.base.readonly_connection` 을 갈아끼워도 소비자에게 닿지 않아 **시험이 조용히
실제 DB 를 쓴다.** 소비자 전부가 정의 모듈을 통해 참조하도록 통일했다
(`service/api/__init__.py` 는 이 이름을 재수출하지 않는다).

**Status:** Active.
