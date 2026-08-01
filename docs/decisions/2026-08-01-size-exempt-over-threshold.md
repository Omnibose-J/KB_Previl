# 400줄 문턱을 올리지 않고 사유 붙은 면제 목록을 둔다

**Decision:** 2026-08-01. 출하 파일 길이 상한 `MAX_LINES = 400` 을 유지하고,
그보다 긴 단일 책임 파일은 `tools/manifest.py:SIZE_EXEMPT` 에 **한 줄 사유와
함께** 등록해 통과시킨다. 사유 없이 넘는 파일이 하나라도 있으면 게이트가 깨진다.
등록해 놓고 실제로는 400줄 이하가 된 항목도 게이트가 «면제 불필요» 로 잡는다.

**Context:** 주석 제거 뒤에도 11개 파일이 400줄을 넘었다. 소유자가 «너무 강박적
으로 갓파일 분해할 필요는 없다. 적절한 책임분산과 효율적으로 돌아가는 게 목표»
라고 범위를 조정했다.

**Why:**
- 문턱을 500 이나 600 으로 올리면 **지금 통과시키려고 자를 바꾸는 것**이고,
  다음에 700줄짜리가 들어와도 아무도 모른다. 상한은 그대로 두고 예외를 이름으로
  적으면 목록 자체가 검토 대상이 된다.
- 판정 기준은 줄 수가 아니라 **책임이 섞였는가** 다. `service/api.py` 는 7개
  도메인이라 나눴고, `service/schemas.py`(569줄)·`frontend/api/types.ts`(458줄)
  는 선언만 있어 나누면 import 만 늘고 읽기가 나아지지 않는다.
- 프론트 화면 둘(`S4Detail` 774줄 · `S5Compare` 621줄)은 카드가 이미 별도
  컴포넌트로 나와 있어 화면 자체는 조립이다. **더 중요한 건 이쪽에 시험이
  없다는 것**이다 — 마감 이틀 전에 안전망 없이 가르는 것이 안 가르는 것보다
  위험하다. 사유에 그대로 적었다.

**Rejected:**
- *문턱 상향* — 위. 자를 바꾸는 것은 측정이 아니다.
- *게이트 삭제* — 새로 생기는 갓파일을 못 잡는다. 이 저장소는 이미 한 번
  1,165줄까지 자랐다.
- *11개 전부 분해* — 소유자가 명시적으로 범위를 좁혔고, 얻는 것보다 마감 직전
  회귀 위험이 크다.

**현재 면제 11건:** `service/schemas.py` · `frontend/app/src/api/types.ts` ·
`S4Detail.tsx` · `S5Compare.tsx` · `GoodwillCard.tsx` · `model/asof.py` ·
`model/party.py` · `model/recovery.py` · `pipeline/bootstrap.py` ·
`pipeline/addr_history.py` · `service/precompute.py`

**Status:** Active. 관련 [[2026-08-01-api-module-to-package]] ·
[[criteria-submission-repack-v1]].
