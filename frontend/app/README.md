# KB 터 프론트엔드 (레인 C)

스펙: `../design/ui-spec.md` (계약 전체) · 이 골격은 스펙 §7 부록의 계약을 코드로 옮긴 것.

```bash
npm install
npm run dev        # http://localhost:5173 — /api는 FastAPI(8000)로 프록시
```

백엔드가 없으면 화면은 **에러 상태를 그린다 — 그게 정상이다.** 목 데이터·폴백을 추가하지 말 것(스펙 §1). 백엔드 실행: `uvicorn service.app:app --reload --port 8000` (저장소 루트에서).

| 위치 | 역할 |
|---|---|
| `src/api/` | B→C 계약 (types = 잠정 스키마, B가 `lanes/B-backend.md`에 확정하면 1:1 갱신) |
| `src/components/` | 계약 컴포넌트 — 상태 카피·등급 포맷·한계 스트립은 스펙 고정값 |
| `src/screens/` | S1~S4 자리 — 각 파일 머리의 스펙 참조 주석이 작업 지시서 |
| `../design/tokens/tokens.css` | 디자인 토큰 단일 출처 (여기로 import, 복사 금지) |
