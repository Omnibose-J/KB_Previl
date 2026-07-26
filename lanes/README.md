# 3-레인 병렬 작업 규칙

세 레인이 동시에 움직인다. 충돌은 대부분 **두 사람이 같은 파일을 쓸 때** 생기므로, 규칙은 하나로 요약된다 — **자기 레인 폴더만 쓴다.**

| 레인 | 소유 폴더 | 산출물 | 진입 문서 |
|---|---|---|---|
| **A. 알고리즘·백테스트** | `model/` | `grid_score` 테이블 · 검증 리포트 | `lanes/A-algorithm.md` |
| **B. 백엔드** | `service/` | 조회 API | `lanes/B-backend.md` |
| **C. 프론트엔드** | `frontend/` | 화면 | `lanes/C-frontend.md` |

## 공유 자산 — 아무도 단독으로 바꾸지 않는다

| 경로 | 성격 | 규칙 |
|---|---|---|
| `pipeline/` | 데이터 생성. 검증 통과 상태 | **변경 전 협의.** 바꾸면 `verify`/`consistency` 재실행 필수 |
| `probe/` | 실측 근거 | **읽기 전용.** 수정 금지 |
| `docs/` | 문서 | 자기 레인 문서만 수정. 공용 문서는 협의 |
| `kb.db` · `pipeline/cache/` | 데이터 (gitignore) | 레인 A만 쓴다. B·C는 읽기만 |
| `.env` | 키 (gitignore) | 절대 커밋 금지 |

## 레인 간 계약

```
레인 A ──[ grid_score 테이블 ]──> 레인 B ──[ HTTP API ]──> 레인 C
```

**A → B: `grid_score`**  (스키마 고정, 변경 시 B에 통보)
```sql
grid_score(uptae TEXT, grid_id TEXT, score REAL, grade INTEGER, observed REAL)
score_meta(k TEXT, v TEXT)   -- as_of, observed_by_grade, overall_survival
```
A가 모델을 바꿔도 이 스키마만 유지하면 B는 영향받지 않는다. 재계산은 `python -m service.precompute` (84초).

**B → C: HTTP API**  — **스펙 미확정.** 협의 문서 나오면 그때 확정한다. 그 전까지 C는 `docs/ui-data-contract.md`의 "제공 가능한 데이터" 목록으로 화면을 설계한다.

## 병렬 실행 방식

**기본: 단일 트리 + 폴더 분리.** 파일이 겹치지 않으므로 대부분 이걸로 충분하다.

**에이전트를 동시에 여러 개 돌린다면 git worktree를 쓴다** — 한 트리에 두 writer를 두면 git 상태가 엉킨다.
```powershell
powershell -File lanes/setup-worktrees.ps1
```
`kb.db`(229MB)와 `pipeline/cache/`(807MB)는 gitignore라 worktree에 복사되지 않는다. 스크립트가 `KB_DB`/`KB_CACHE`/`KB_ENV` 환경변수로 원본을 가리키게 설정한다.

## 하지 말 것

- 다른 레인 폴더 수정 — 필요하면 그 레인에 요청
- `pipeline/` 무단 변경 — 세 레인의 기반이 흔들린다
- `kb.db`를 B·C에서 쓰기 — 읽기만
- 검증 우회 — `verify` 8/8 · `consistency` 17/17 · 누수 가드는 항상 통과 상태여야 한다

## 공통 확인 명령

```bash
python -m pipeline.verify        # 적재 8종
python -m pipeline.consistency   # 논리 정합성 17종
python -m model.test_leakage     # 누수 가드
```
