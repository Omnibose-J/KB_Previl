# KB Previl — 서울 요식업 입점 위치 추천

> 이 파일은 **제출 zip 의 루트 README** 다. `scripts/package_submission.py` 가
> zip 안에서 `README.md` 로 넣는다. 저장소 루트의 `README.md`(개발자용)와 다르다.

서울 어느 지점이든 **100m 격자** 단위로 음식점 입지를 평가하고, **과거 데이터로
검증된** 등급을 매긴다. 등급은 의견이 아니라 실측이다 — 1등급 자리의 3년 생존율은
**76.9%**, 10등급은 **28.4%** 였다(2023년 개업 코호트, 홀드아웃).

---

## ① 데모 실행 — 2분, 인터넷 없이도 대부분 동작

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
python -m uvicorn service.app:app --port 8000
```

브라우저에서 **http://localhost:8000** 을 연다. 그게 전부다.

- **API 키가 필요 없다.** 동봉된 `kb-demo.db` 를 읽기 전용으로 조회한다.
- **빌드가 필요 없다.** 프론트엔드 번들(`frontend/app/dist`)이 동봉돼 있고 같은
  서버가 서빙한다. `npm install` 을 하지 않아도 된다.
- 화면 흐름: 랜딩 → 업종·지역 입력 → 추천 목록(지도) → 자리 상세 → 비교.

**인터넷이 없을 때 무엇이 안 되는가**: 지도 배경 타일이 안 나온다(OpenStreetMap).
격자·등급·추천·손익·권리금은 전부 로컬 계산이라 정상 동작한다.

**API 키를 넣으면 추가되는 것 하나**: `.env` 에 `OPENAI_API_KEY` 를 넣으면 상세
화면의 «근거 문장»(`POST /api/report`)이 켜진다. 키가 없으면 그 카드만 오류를
표시하고 나머지는 그대로다. 숫자는 전부 서버가 계산하며 **LLM 은 문장만 만든다.**

API 문서는 서버를 띄운 뒤 http://localhost:8000/docs 에 있다.

---

## ② 검증 재현 — 게이트만 먼저

동봉 DB 로 바로 돌릴 수 있는 것:

```bash
pip install -r requirements-full.txt
KB_DB=kb-demo.db python -m pytest service -q      # 서빙 계약 96종
```

모델·파이프라인 게이트는 **전체 DB 가 필요하다**(`kb-demo.db` 는 서빙용 14개
테이블만 담는다). 전체를 만들려면:

```bash
cp .env.example .env      # 공개 API 키 4종을 채운다
python -m pipeline.bootstrap --preflight   # 키·경로·잔여 쿼터 점검 (네트워크 호출 없음)
python -m pipeline.bootstrap --gates       # 수집 → … → grid_score → 게이트
```

**하루로는 끝나지 않는다.** 서울 열린데이터는 일일 900콜인데 실측 소요가 857콜이고,
`ui_curves` 한 단계만 895초다. 중간에 끊기면 다음 날 같은 명령을 다시 치면
이어서 받는다.

만들고 나면:

```bash
python -m pipeline.verify              # 적재 8종
python -m pipeline.consistency         # 논리 정합성 17종
python -m model.test_leakage           # 누수 가드 RED→GREEN
python -m model.asof --selftest-cut    # T 이후 행을 지워도 값 불변
python -m model.backtest --model gbm --features DEPLOY   # 십분위 실측 생존율
```

---

## ③ 결과와 판단 근거

| 문서 | 내용 |
|---|---|
| `docs/model-findings.md` | **실험 대장 — 시도한 전부와 판정.** 기각된 것이 채택된 것보다 훨씬 많다 |
| `docs/data-inventory.md` | 원천별 실측 · 공간해상도 판정 |
| `docs/serving-design.md` | 모델 ↔ 백엔드 계약 (무엇을 하면 안 되는가) |
| `docs/tracking/findings.md` | 발견했으나 소유 범위 밖이라 못 고친 문제 |
| `docs/figures/` | 기술설명서 그림 7장 |

### 함께 읽어야 할 한계

1. **1등급 자리에서도 약 23% 가 3년 내 폐업**한다. 10등급에서도 28.4% 는 살아남는다.
2. **AUC 0.6369 는 «무작위보다 나은 수준»**이지 «잘 맞힌다»가 아니다. 그리고 이 값은
   게을러서가 아니라 **측정된 상한**이다 — 학습 데이터 2.7배·정규화 24설정·
   하이퍼파라미터 70조합·딥러닝을 시도했고 홀드아웃 상위10% 는 움직이지 않았다
   (`docs/figures/fig7-learning-curve.png`).
3. **검증된 예측은 100m 격자에서 멈춘다.** 건물·층은 사실과 서울 전체 통계로만 제공한다.
4. **매출은 상권 단위**라 같은 상권 안 격자는 그 축에서 동점이다.
5. **상권 밖 49.5% 는 매출 기반 기능(부담률·권리금)을 제공하지 않는다** — 비워서 보여준다.
6. **비정형으로 예측하려는 시도는 아홉 번 모두 기각됐다.** 이유도 측정했다: 검색 관심도와
   실제 유동인구의 상관이 ρ=+0.079 다.
7. **`visitorParty`는 예측이 아닌 표기 전용 관측이다.** §J-1에서 `family`(정밀도
   0.633)와 `work`(0.700)만 표기 문턱을 통과해 화면에 정확도와 함께 나가며,
   `alone`·`couple`·`friend`는 기각됐다. 방문객 관점의 상권 단위 값이고 순위에는
   쓰지 않는다. **비정형 예측 검정 누계 13건 · 채택 0 은 그대로다.** 표기 문턱의
   통과이지 피처 문턱의 통과가 아니다.

---

## 동봉물

```
kb-demo.db              서빙용 경량 DB (14개 테이블 · 원본 445MB 중 필요분만)
requirements.txt        데모 실행용
requirements-full.txt   파이프라인·모델 재현용
.env.example            키 형식 (실제 키는 포함되지 않는다)
service/                조회 API — 모델을 적합하지도 호출하지도 않는다
model/                  라벨·as-of 복원·학습·검증 하니스
pipeline/               수집 → 정규화 → 격자 → 피처
probe/                  실측 근거 (좌표계 판정 등)
frontend/app/dist/      빌드된 화면 (그대로 서빙됨)
frontend/app/src/       화면 소스
docs/                   설계·실험 기록·발견 사항
```

`.env`, 전체 `kb.db`, 수집 캐시, `node_modules` 는 **의도적으로 제외**했다.
