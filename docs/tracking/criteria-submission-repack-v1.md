# 수용 기준: 제출물 재구성 (서비스 zip / DB zip / .env)

목표: 심사자가 **코드 zip · DB zip · `.env` 세 개를 같은 폴더에 풀고 `run.py` 하나를
실행하면** 다른 컴퓨터에서도 동일하게 서비스가 뜬다. zip 안에는 제품 코드만 있고
실험 코드·설계 문서·설계 의도 주석은 없다.

마감 2026-08-03 16:00.

## 산출물 3종

**기본은 합본이다** (`python build.py --rehearse`). 저장 공간 때문에 분리본은
남기지 않는다 — 빌드할 때마다 다른 형태의 낡은 산출물을 지운다.

| # | 이름 | 실측 | 내용 |
|---|---|---|---|
| 1 | `KB_Previl_all.zip` | 89.9MB · 1,135항목 | `previl/` 하나로 풀린다 — 백엔드 · 프론트 소스 · 빌드본(`web/`) · `run.py` · `verify.ipynb` · `kb-demo.db` |
| 2 | `.env` | 738B · 키 9종 | **zip 에 들어가지 않는다** |

나누어 내야 하면 `python build.py --split --rehearse` — `KB_Previl_service.zip`
(20.9MB) + `KB_Previl_db.zip`(69.1MB) + `.env` 3종이 되고, 이때는 zip 검사가
`kb-demo.db` 를 다시 금지 항목으로 본다.

README 는 zip 이 하나든 둘이든 같은 문서로 안내한다. 리허설도 실제로 낼 zip 을
풀어 검사한다.

## 완료 조건

- [x] 코드 zip 에 제품 경로 밖 모듈이 0개 — probe·실험 58개, `pipeline/run.py` 미포함
      → `python -m tools.audit --closure` exit 0 · 진입점 도달 48/106
- [x] 코드 zip 에 설계 문서 0개 — `docs/` `lanes/` `frontend/design/` 미포함, 루트 `README.md` 1개만
      → 출하 목록에 없음 + `--zip` 게이트가 `.md`(README 제외)·`docs`·`lanes` 를 거부
- [x] 코드 zip 에 `.env` · `kb.db` · `kb-demo.db` · 캐시 0건
      → `gate_zip` FORBIDDEN_NAMES/DIRS
- [x] 출하 소스에 주석·독스트링 0건 — 패키징 때 기계적으로 제거하고 모듈당 영어 한 줄만 남긴다
      → `python -m tools.audit --comments` exit 0 · 19,047줄 → 16,921줄 (2,126줄 제거)
- [x] 갓파일 없음 — 출하 파일 중 400줄 초과가 **사유 없이는** 0개
      → `python -m tools.audit --size` · 면제 11 · 위반 0
      → 분해한 것은 둘뿐이다. `service/api.py` 1,165 → 6개 모듈(base·context·cells·meta·search·changes),
        `service/app.py` 839 → 379 + `schemas.py` 569. 나머지는 길지만 단일 책임이라
        `SIZE_EXEMPT` 에 사유와 함께 남겼다 — 문턱을 올리지 않았으므로 새 갓파일은 계속 걸린다.
- [x] 주석 제거가 동작을 바꾸지 않았다 — 벗겨낸 트리에서 기존 서빙 계약이 그대로 통과
      → `python -m tools.audit --behaviour` exit 0 · `121 passed`
- [x] 주석 제거가 프론트 소스도 망가뜨리지 않았다
      → `python -m tools.audit --frontend` exit 0 · 벗겨낸 `src` 로 `tsc --noEmit`
      → 파이썬은 제거 후 `ast.parse` 로 확인되지만 TS 는 확인할 파서가 없었다.
        줄 첫 글자가 `*` 인 연산자 연속행처럼 주석이 아닌 줄이 지워져도 zip 은
        조용히 나간다 — 그 구멍을 게이트로 막았다.
- [x] `run.py` 하나로 셋업 + 기동
      → `python build.py --rehearse` · 빈 폴더에 3종을 풀고 새 venv 로 부팅:
        `/api/meta` 200 · `/api/recommend` 200 (24건) · UI 200 · `/api/grids` 200 (45칸) · 지도 워커 2개
- [x] DB 가 없을 때 `run.py` 가 스스로 백필을 시작한다
      → `run.py:backfill()` 이 부르는 두 단계를 직접 확인:
        `python -m pipeline.bootstrap --preflight` → **사전 점검 PASS**,
        `python -m pipeline.bootstrap --plan` → 18단계와 각 단계 완료 여부 출력
      → 주: 완주는 서울 쿼터 일 900콜 / 소요 857콜 때문에 하루 이상이라 **끝까지는 못 돌린다.**
        진입과 계획 출력까지가 증거이고 README «4. 더 해 볼 수 있는 것» 에 소요를 적었다.
        개발 트리는 캐시 7/7 종이 있어 «약 0콜» 로 나오지만, 캐시 없는 심사자 PC 는 857콜이다.
- [x] 최소 검증물 `verify.ipynb` 한 개가 위에서 아래로 전부 통과
      → `python -m nbconvert --to notebook --execute verify.ipynb` exit 0 · PASS 5종 · 그래프 4장 · 오류 0
- [x] 리팩터가 서빙 동작을 바꾸지 않았다
      → `python -m pytest service -q` **121 passed** · `python -m pipeline.consistency` **17/17 PASS**

## 코드 리뷰 2차 (codex, 2026-08-01) 지적과 처리

1차 감사가 통과시킨 것을 2차가 잡았다. **결론은 «재패키징 완료로 승인 불가» 였고
그것이 옳았다** — 당시 zip 은 «주석 0건» 계약을 어기고 있었는데 게이트가 통과시켰다.

| 지적 | 재현 | 처리 |
|---|---|---|
| **TS/TSX 주석이 zip 에 남는다.** 줄 모양 검사라 인라인 `//` 와 JSX `{/* */}` 를 통째로 놓쳤다 | 재현됨 — 실측 **17파일 132줄** (리뷰 보고는 12/48) | 휴리스틱 폐기. **TypeScript 컴파일러**로 주석 range 를 뽑아 제거 |
| **`strip_ts` 가 `* 3` 같은 곱셈 연속행을 지운다.** 남은 코드가 여전히 문법이 맞아 빌드가 통과한다 | 재현됨 | 위와 같이 해결. 실제로 화면 각주 «`* 5년 숫자는…`» 두 줄이 지워질 뻔했다 |
| 같은 줄 독스트링(`"""doc"""; x = 1`)이 코드까지 지운다 | 재현됨 | 추측하지 않고 **위치를 찍어 실패**시킨다 |
| `from __future__` 뒤에 헤더를 넣어 독스트링이 되지 않는다. 괄호형은 구문 오류 | 재현됨 | 헤더를 future import 앞에 넣고 셔뱅을 보존 |
| CSS 이스케이프·토큰 경계 오처리 | 재현됨 | **postcss** 로 교체. 값 안 주석은 토큰이 붙을 수 있으므로 위치를 찍어 거부 |
| **전제가 없으면 게이트가 성공을 반환한다** (zip 없음·DB 없음·node_modules 없음) | 재현됨 | 전부 실패로. «검사 못 함» 을 통과로 세지 않는다 |
| `gate_zip` 이 계약을 거의 안 본다 — 빈 zip·루트 밖 파일·경로 탈출 통과 | 재현됨 | 최상위 하나 · 필수 7항목 · 중복 · CRC · 경로 탈출 · 합본 DB 단일성 검사 추가 |
| **audit 과 package 가 출하 집합을 각자 계산해 어긋난다** (`vite.config.ts`·`tokens.css`) | 재현됨 | `ship_items()` 한 함수로 합침. 게이트가 보는 파일 = zip 에 들어가는 파일 |
| `errors="ignore"` 가 깨진 바이트를 지워 다른 유효 코드가 될 수 있다 | 코드 확인 | strict 로 |
| `build.py` 에 UTF-8 재구성이 없어 cp949 리다이렉트에서 죽는다 | 재현됨 | 추가 |
| `.env` 부재 시 낡은 사본을 남기고 성공 반환 | 재현됨 | 낡은 것을 지우고 실패 반환 |
| 리허설이 업종 없으면 «한식» 으로 때워 계약 파손을 덮는다 | 재현됨 | 대체값 제거, 없으면 실패 |
| `build_web` 신선도가 `src/` 만 본다 | 코드 확인 | 토큰 CSS·설정·`index.html`·`public/` 포함 |
| POSIX 에서 손자 프로세스가 안 죽는다 | 코드 확인 | `start_new_session` + `killpg` |
| `STAMP` 가 mtime 기반이라 내용 변경을 놓친다 | 코드 확인 | 내용 해시로 |
| `model/party.py` 면제 사유가 실제와 다르다 | 확인 | 사유를 정직하게 다시 씀 — 단일 책임이 아니고, 서빙 경로 밖이라 분해를 미룬 것이다 |

**얻은 교훈:** 첫 감사와 두 번째 리뷰가 모두 「주석 제거」를 봤지만, 잡은 것은
두 번째뿐이었다. 차이는 **게이트를 믿었느냐 아니면 zip 바이트를 직접 열었느냐** 다.
그래서 잔여 주석 검사도 모양 검사에서 **재제거 후 동일한가(멱등성)** 로 바꿨다 —
하나라도 남아 있으면 두 번째 통과가 지워서 결과가 달라진다.

## 독립 감사 1차 (fable, 2026-08-01) 지적과 처리

감사는 `e40d2ad`·`21aea0c` 를 대상으로 돌았고 7개 확인 항목 중 2건을 FAIL 로
판정했다. 전부 재현해 확인한 뒤 고쳤다.

| 지적 | 확인 | 처리 |
|---|---|---|
| **CSS 24개에 한글 서사 주석 255줄이 zip 에 실림.** `STRIPPED` 와 `ship_paths()` 가 py·ts 만 봐서 게이트가 CSS 를 아예 안 봤다 | 재현됨 (255줄) | `strip_css` 추가(문자열 안 `/*` 를 건드리지 않는 상태 기계), CSS 를 게이트·패키징 범위에 포함. **255 → 0** |
| **캐시 2개 혼입** — `.ruff_cache/CACHEDIR.TAG`·`tsconfig.tsbuildinfo`. `gate_zip` 이 블록리스트라 못 잡았다 | 재현됨 | `TREE_EXCLUDE` 보강 + `gate_zip` 에 **확장자 허용 목록** 추가 — 모르는 확장자는 세운다 |
| **`.env` 에 타 프로젝트 키 7종과 개인 경로 노출** | 재현됨 | `stage_env()` 가 출하 코드에서 읽는 키를 스캔해 그것만 남긴다. 9종 유지 · 7종 제외 (KRX·ECOS·YouTube·OpenDART·VWorld·Google Maps·Kakao JS) |
| preflight 가 마지막 단계 party 의 키를 안 본다 — 하루 넘게 돌고 마지막에 죽을 수 있다 | 코드 확인 | `REQUIRED_ENV_KEYS` 에 NAVER 2종·OPENAI 추가 |
| `run.py` 만 stdout 재구성이 없어 리다이렉트 시 죽을 수 있다 | 코드 확인 | `use_utf8()` 추가 + uvicorn 에 `PYTHONIOENCODING` 전달 |
| `manifest.py` 주석이 «두 zip 모두 previl 로 풀린다» 라고 잘못 적음 | 확인 | 주석 정정 |

**감사가 못 본 것을 새 게이트가 잡았다.** 프론트 게이트를 `tsc` 에서
`tsc + vite build` 로 올리자 **`main.tsx:5` 가 `frontend/app` 바깥의
`../../design/tokens/tokens.css` 를 부르는데 그 파일이 zip 에 없었다** —
심사자가 프론트를 빌드하려 하면 실패했다. 출하 레이아웃을 저장소와 같게
되돌리고(`frontend/app` → `frontend/app`) 토큰 CSS 를 동봉해 고쳤다.

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
