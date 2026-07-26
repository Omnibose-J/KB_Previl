# KBFG 서체

KB금융그룹 전용서체(KB금융 본문체). 원본 OTF는 <https://www.kbfg.com/kor/about/corporate/font.htm> 에서 받는다.

## 지금 들어있는 것

| 파일 | 내부 typo family | weight |
|---|---|---|
| `KBFGText-Light.woff2` | KBFG Text | 300 |
| `KBFGText-Medium.woff2` | KBFG Text | 500 |

OTF → woff2 변환(용량 약 1/5):

```bash
python -c "from fontTools.ttLib import TTFont; t=TTFont('KBFGText-Light.otf'); t.flavor='woff2'; t.save('KBFGText-Light.woff2')"
```

## 굵기가 300·500 두 종뿐이라 생긴 제약

Bold(700)·제목체(KBFG Display)는 공개 배포본에 없다. 700을 지정하면 브라우저가 합성 볼드를 그리는데, 획이 조밀한 한글은 본문 크기에서 속공간이 메워져 뭉갠다.

그래서 `global.css`가 `font-synthesis: none`으로 합성을 끄고, `tokens.json`의 `font.weight`는 **bold·black도 500**으로 매핑돼 있다. 위계는 굵기가 아니라 **300↔500 대비 + 크기 + 색**이 만든다.

Bold나 Display를 나중에 구하면: 이 폴더에 woff2를 넣고 → `src/styles/fonts.css`에 `@font-face` 한 벌 추가 → `tokens.json`의 `font.weight.bold`를 700으로 되돌리고 `build-css.ps1` 실행. 그 세 곳 말고는 고칠 데가 없다.

`@font-face`는 **실제로 있는 파일만** 선언한다 — 없는 파일을 선언하면 매 로드마다 404가 난다.
