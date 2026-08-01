# 수용 기준: 제출물 재구성 (서비스 zip / DB zip / .env)

목표: 심사자가 **코드 zip · DB zip · `.env` 세 개를 같은 폴더에 풀고 `run.py` 하나를
실행하면** 다른 컴퓨터에서도 동일하게 서비스가 뜬다. zip 안에는 제품 코드만 있고
실험 코드·설계 문서·설계 의도 주석은 없다.

마감 2026-08-03 16:00.

## 산출물 3종

| # | 이름 | 내용 |
|---|---|---|
| 1 | `KB_Previl_service.zip` | `previl/` 하나로 풀린다 — 백엔드 · 프론트 소스 · 빌드본(`web/`) · `run.py` · `verify.ipynb` |
| 2 | `KB_Previl_db.zip` | `kb-demo.db` 단일 파일 (폴더로 감싸지 않는다) |
| 3 | `.env` | API 키 — **어느 zip 에도 들어가지 않는다** |

빌드·검사는 전부 `python build.py [--rehearse]` 하나로 돈다.

## 완료 조건

- [x] 코드 zip 에 제품 경로 밖 모듈이 0개 — probe·실험 58개, `pipeline/run.py` 미포함
      → `python -m tools.audit --closure` exit 0 · 진입점 도달 48/106
- [x] 코드 zip 에 설계 문서 0개 — `docs/` `lanes/` `frontend/design/` 미포함, 루트 `README.md` 1개만
      → 출하 목록에 없음 + `--zip` 게이트가 `.md`(README 제외)·`docs`·`lanes` 를 거부
- [x] 코드 zip 에 `.env` · `kb.db` · `kb-demo.db` · 캐시 0건
      → `gate_zip` FORBIDDEN_NAMES/DIRS
- [x] 출하 소스에 주석·독스트링 0건 — 패키징 때 기계적으로 제거하고 모듈당 영어 한 줄만 남긴다
      → `python -m tools.audit --comments` exit 0 · 19,047줄 → 16,921줄 (2,126줄 제거)
- [ ] 갓파일 없음 — 출하되는 `.py`·`.tsx` 중 400줄 초과 0개
      → `python -m tools.audit --size` · **현재 12개 남음**
- [x] 주석 제거가 동작을 바꾸지 않았다 — 벗겨낸 트리에서 기존 서빙 계약이 그대로 통과
      → `python -m tools.audit --behaviour` exit 0 · `121 passed`
- [ ] `run.py` 하나로 셋업 + 기동
      → `python build.py --rehearse` · 빌드·압축 해제·venv·pip 까지 통과, 최종 기동 확인 대기
- [ ] DB 가 없을 때 `run.py` 가 스스로 백필을 시작한다
      → `python run.py --backfill-only --dry-run`
      → 주: 완주는 서울 쿼터 일 900콜 / 소요 857콜 때문에 하루 이상이라 **끝까지는 못 돌린다.** 진입과 계획 출력까지만 증거로 삼고 README 에 소요를 명시한다
- [x] 최소 검증물 `verify.ipynb` 한 개가 위에서 아래로 전부 통과
      → `python -m nbconvert --to notebook --execute verify.ipynb` exit 0 · PASS 5종 · 그래프 4장 · 오류 0
- [ ] 리팩터가 서빙 동작을 바꾸지 않았다 — 저장소의 기존 게이트가 그대로 초록
      → `python -m pytest service -q` · `python -m pipeline.consistency`

## 실측으로 잡은 결함 (리허설이 없었으면 심사자가 먼저 만났을 것)

1. **pip 가 한글 `requirements.txt` 를 읽지 못한다.** 한국어 윈도에서 pip 는 BOM 없는
   파일을 cp949 로 디코딩하므로 `UnicodeDecodeError` 로 첫 설치가 죽는다.
   → requirements 3종을 ASCII 로 고정. 한국어 설명은 README 가 맡는다.
2. **리허설이 손자 프로세스를 남긴다.** `run.py` 가 uvicorn 을 또 낳아서 부모만
   종료하면 DB 를 붙든 채 남는다. → 윈도에서 `taskkill /T` 로 트리 종료.

## 범위 밖 (건드리지 않음)

- **모델 재학습·수치 변경.** AUC 0.6383 · 1등급 80.1% · 마진 +0.0714 는 그대로 간다
- **저장소에서 실험 코드 삭제.** 68개 모듈·`docs/`·`lanes/` 는 저장소에 남는다 (zip 에서만 제외)
- **기존 테스트 스위트 121종 삭제.** 저장소에 남겨 리팩터의 안전망으로 쓴다. zip 에는 `verify.ipynb` 만 나간다
- 기술설명서 문서 · 데모 영상 · 프론트엔드 디자인 변경 · 새 기능

## 제약 (3단계 경계)

- ✅ **항상**: 리팩터 커밋 전 `pytest service -q` 실행 · 파일 이동은 git mv · 출하 문구는 한국어
- ⚠️ **먼저 확인**: `git push` · `.env` 를 다루는 모든 작업 · zip 파일명 변경
- 🛑 **절대**:
  - 테스트를 고쳐서 통과시키지 않는다 (약화·삭제·기대값 하드코딩·특수분기)
  - `.env` 를 git 에 커밋하지 않는다 — 제출 채널과 저장소는 별개다
  - 게이트 우회 금지. 리팩터로 깨진 것은 리팩터를 고친다
  - 주석 게이트를 통과시키려고 **필요한 설명까지 지우지 않는다** — 지우는 것은 서사이고, 남기는 것은 «이 함수가 무엇을 하는가» 다

## 건드릴 파일

```
service/        app.py·api.py 분해 → routes/ schemas/ query/
model/ pipeline/ 출하분 주석 정리 (로직 불변)
frontend/app/src/  주석 정리 · 400줄 초과 화면 분해
run.py          신규 — 단일 진입점
verify.ipynb    신규 — 최소 검증물
tools/          신규 — audit(게이트) · package(3종 빌드 + 리허설)
scripts/package_submission.py → tools/package.py 로 대체
```
