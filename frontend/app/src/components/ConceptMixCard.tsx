import { useState } from "react";
import type { ConceptMix } from "../api/types";
import { int } from "../lib/format";
import s from "./ConceptMixCard.module.css";

// 주변 점포 구성. 서버가 준 개수만 그린다 — 비율·순위·전망을 클라이언트에서
// 만들지 않는다. 이 값은 상호명으로 분류한 영업중 점포를 센 관측이고 등급·
// 생존율과 연결하지 않는다(docs/unstructured-plan.md §I-24·§I-26).

const TOP_N = 6;

export default function ConceptMixCard({ mix }: { mix: ConceptMix | null }) {
  const [expanded, setExpanded] = useState(false);

  // 배치 미실행과 "구성이 잡히지 않는 자리"는 다른 상태다. 같은 문구로 뭉개면
  // 데이터가 없는 것을 이 동네에 가게가 없다고 읽게 된다.
  if (!mix || !mix.available) {
    return (
      <section className={s.card}>
        <div className={s.head}>
          <h2>이 주변엔 어떤 가게가 있나요</h2>
        </div>
        <p className={s.unavailable}>점포 구성 데이터를 아직 준비하지 못했어요.</p>
      </section>
    );
  }

  if (mix.items.length === 0) {
    return (
      <section className={s.card}>
        <div className={s.head}>
          <h2>이 주변엔 어떤 가게가 있나요</h2>
        </div>
        <p className={s.unavailable}>
          이 자리 주변에는 상호명으로 종류를 알 수 있는 가게가 없어요.
        </p>
      </section>
    );
  }

  const shown = expanded ? mix.items : mix.items.slice(0, TOP_N);
  const max = mix.items[0].shops;

  return (
    <section className={s.card}>
      <div className={s.head}>
        <h2>이 주변엔 어떤 가게가 있나요</h2>
        <p>걸어서 갈 거리에 영업 중인 가게 {int(mix.shops)}곳을 종류별로 세어봤어요.</p>
      </div>

      <div className={s.rows}>
        {shown.map((item, i) => (
          <div key={item.concept} className={s.row}>
            <span className={s.name}>{item.concept}</span>
            <span className={s.track}>
              <span
                className={i === 0 ? `${s.fill} ${s.fillTop}` : s.fill}
                style={{ width: `${(item.shops / max) * 100}%` }}
              />
            </span>
            <span className={s.count}>{int(item.shops)}곳</span>
          </div>
        ))}
      </div>

      {mix.items.length > TOP_N ? (
        <button className={s.more} onClick={() => setExpanded(!expanded)}>
          {expanded ? "접기" : `${mix.items.length - TOP_N}종 더 보기`}
        </button>
      ) : null}

      <p className={s.note}>
        가게 이름으로 종류를 알 수 있는 곳만 세어서 실제보다 적게 나와요. 지금 문 연
        가게 기준이고, 잘 되는 자리인지와는 별개예요.
      </p>
    </section>
  );
}
