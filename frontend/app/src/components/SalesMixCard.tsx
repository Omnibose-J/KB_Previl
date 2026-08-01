import type { SalesMix } from "../api/types";
import { pct0, quarter } from "../lib/format";
import s from "./SalesMixCard.module.css";

// 「이 주변엔 어떤 가게가 있나요」의 짝. 저쪽은 상호명으로 가게를 세고 이쪽은
// 카드 결제를 센다. 가게 수로 수요를 짐작하면 틀리는 폭이 크다 — 상권 1,185곳
// 에서 커피는 가게 27.8% / 결제 24.7%, 한식은 가게 31.8% / 결제 55.1% 였다.
//
// 서버가 준 share 를 그대로 그린다. 두 카드를 합친 지수는 만들지 않는다 —
// 합치면 무엇을 센 값도 아니게 된다.

const TOP_N = 6;

export default function SalesMixCard({ mix }: { mix: SalesMix | null }) {
  // 상권 밖(격자의 49.5%)과 「상권 안인데 공표가 없다」는 다른 상태다.
  if (!mix || !mix.available) {
    return (
      <section className={s.card}>
        <div className={s.head}>
          <h2>이 상권에선 어디에 돈이 도나요</h2>
        </div>
        <p className={s.unavailable}>
          이 자리는 상권 밖이라 결제 구성을 알 수 없어요.
        </p>
      </section>
    );
  }

  if (mix.items.length === 0) {
    return (
      <section className={s.card}>
        <div className={s.head}>
          <h2>이 상권에선 어디에 돈이 도나요</h2>
        </div>
        <p className={s.unavailable}>
          이 상권은 공표된 업종 매출이 없어요. 점포가 한두 곳뿐인 업종은 개별
          사업자 매출이 드러나 공표되지 않아요.
        </p>
      </section>
    );
  }

  const shown = mix.items.slice(0, TOP_N);
  const max = mix.items[0].share ?? 1;

  return (
    <section className={s.card}>
      <div className={s.head}>
        <h2>이 상권에선 어디에 돈이 도나요</h2>
        <p>
          {mix.quarter ? `${quarter(mix.quarter)}에 ` : ""}이 상권에서 결제된 금액을
          업종별로 나눴어요.
        </p>
      </div>

      <div className={s.rows}>
        {shown.map((item, i) => (
          <div key={item.induty} className={s.row}>
            <span className={s.name}>{item.induty}</span>
            <span className={s.track}>
              <span
                className={i === 0 ? `${s.fill} ${s.fillTop}` : s.fill}
                style={{ width: `${((item.share ?? 0) / max) * 100}%` }}
              />
            </span>
            <span className={s.count}>
              {item.share !== null ? pct0(item.share) : "—"}
            </span>
          </div>
        ))}
      </div>

      {/* 「상권 단위」는 머리말이 이미 말하므로 빼고, 원천의 한계와 이 카드를
          두는 이유만 남긴다. */}
      <p className={s.note}>
        카드 결제 기준이라 현금 거래는 빠져요. 가게가 많은 업종이 돈을 제일 많이 버는
        건 아니에요.
      </p>
    </section>
  );
}
