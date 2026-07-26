# KB 터 프론트엔드 (레인 C)

스펙: `../design/ui-spec.md` (계약 전체) · B의 응답 스키마: `../../lanes/B-backend.md`

```bash
npm install
npm run dev        # http://localhost:5173 — /api는 FastAPI(8000)로 프록시
```

백엔드가 없으면 화면은 **에러 상태를 그린다 — 그게 정상이다.** 목 데이터·폴백을 추가하지 말 것(스펙 §1). 백엔드 실행: `uvicorn service.app:app --reload --port 8000` (저장소 루트에서).

| 위치 | 역할 |
|---|---|
| `src/api/` | B→C 계약. `types.ts`는 `lanes/B-backend.md`의 스키마와 1:1이며, 한쪽만 고치면 조용히 어긋난다 |
| `src/components/` | 계약 컴포넌트 — 상태 카피·등급 포맷·단위 캡션·한계 스트립은 스펙 고정값 |
| `src/screens/` | S1~S4. 각 파일 머리 주석이 그 화면에서 **의도적으로 뺀 것**과 이유를 적어둔다 |
| `src/copy.ts` | 정적 카피. 모델이 산출한 수치는 여기 두지 않는다(§ 아래) |
| `../design/tokens/tokens.css` | 디자인 토큰 단일 출처. `tokens.json` 수정 → `build-css.ps1` 재실행 |

## 화면 수치가 어디서 오는가

생존율·격자 수·등급 경계·한계 문구는 **전부 API 응답**에서 온다. 프론트에 상수로 두면 모델 재계산(실험 라운드) 때 화면만 옛 숫자로 남는다. `src/copy.ts`에 허용되는 것은 재계산이 바꿀 수 없는 **데이터셋 자체의 사실**(원자료 건수·수집 기간·사용한 출처 목록)뿐이다.

단위 캡션("행정동 단위" 등)도 응답의 `resolutions`에서 읽는다 — 필드별 실제 해상도를 아는 쪽은 B다.

## 두 가지 함정

**MapLibre 워커** — `vite.config.ts`의 `optimizeDeps.exclude: ["maplibre-gl"]`을 지우면 지도에 격자가 사라진다. esbuild 사전 번들링이 `new Worker(new URL(...))`를 다시 써서 워커가 **조용히** 죽고, raster 타일은 메인 스레드라 그대로 보이므로 콘솔 에러 없이 "데이터가 없는 것처럼" 보인다.

**지도 도착 줌** — 서울 전역 뷰는 셀 상한(2,000)을 넘어 `/grids`가 413으로 실패한다. 그래서 S3는 추천 1위 격자로 `flyTo`한 상태로 도착한다. 초기 줌을 낮추면 첫 화면이 빈 지도가 되고, 이는 "여긴 데이터가 없다"는 잘못된 주장이 된다.

## 지도

카카오 JS SDK 대신 **MapLibre GL + OSM**을 쓴다 — `KAKAO_JAVASCRIPT_KEY`가 발급되지 않았고, 스펙 §1이 지정한 폴백이다. 키가 나오면 `src/components/GridMap.tsx` 한 파일만 교체하면 된다.

베이스맵은 채도를 죽여 회색으로 깔고, 색은 데이터 레이어만 쓴다. 등급 램프는 KB 블루 10단이며 **브랜드 옐로우는 데이터를 칠하지 않는다** — 옐로우는 CTA와 추천 후보 셀 테두리 전용이다.

## 폰트

KB금융 본문체(KBFG Text) Light·Medium 2종만 공개돼 있다. 굵기 위계 대신 300↔500 대비와 크기·색으로 위계를 만든다. 자세한 제약과 Bold·제목체를 나중에 넣는 방법은 `public/fonts/README.md`.
