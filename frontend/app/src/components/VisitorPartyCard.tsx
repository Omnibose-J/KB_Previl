import type { VisitorParty } from "../api/types";
import { int } from "../lib/format";
import s from "./VisitorPartyCard.module.css";

// 후기에서 «누구와 왔는지»가 적힌 것만 센 관측이다. 비율도 서버가 계산한 share
// 를 쓰고, 순위나 전망을 클라이언트에서 만들지 않는다.
//
// 정확도를 반드시 함께 낸다. 라벨만 보이면 «측정했다»가 «맞다»로 읽히는데,
// 실측 정밀도는 0.633·0.700 이라 10건 중 3~4건은 틀린다.

function accuracyLine(items: VisitorParty["items"]): string {
  const worst = Math.min(...items.map((i) => i.precision));
  const wrong = Math.round((1 - worst) * 10);
  return `후기 글에서 자동으로 골라낸 값이라 10건 중 ${wrong}건쯤은 틀려요.`;
}

export default function VisitorPartyCard({ party }: { party: VisitorParty | null }) {
  // 수집 미실행과 «글이 모자란 자리» 는 다른 상태다. 같은 문구로 뭉개면 준비가
  // 안 된 것을 «이 동네엔 그런 손님이 없다» 로 읽게 된다.
  if (!party || !party.available) {
    return (
      <section className={s.card}>
        <div className={s.head}>
          <h2>여긴 누구와 오는 자리인가요</h2>
        </div>
        <p className={s.unavailable}>후기 데이터를 아직 준비하지 못했어요.</p>
      </section>
    );
  }

  if (party.items.length === 0 || party.labelled === 0) {
    return (
      <section className={s.card}>
        <div className={s.head}>
          <h2>여긴 누구와 오는 자리인가요</h2>
        </div>
        <p className={s.unavailable}>
          이 근처는 후기가 적어서 누구와 오는지까지는 알기 어려워요.
        </p>
      </section>
    );
  }

  const max = Math.max(...party.items.map((i) => i.posts));

  return (
    <section className={s.card}>
      <div className={s.head}>
        <h2>여긴 누구와 오는 자리인가요</h2>
        <p>
          이 상권 후기 {int(party.postsScanned)}개 중 누구와 왔는지 적힌{" "}
          {int(party.labelled)}개를 세어봤어요.
        </p>
      </div>

      <div className={s.rows}>
        {party.items.map((item, i) => (
          <div key={item.party} className={s.row}>
            <span className={s.name}>{item.label}</span>
            <span className={s.track}>
              <span
                className={i === 0 ? `${s.fill} ${s.fillTop}` : s.fill}
                style={{ width: `${(item.posts / max) * 100}%` }}
              />
            </span>
            <span className={s.count}>
              {item.share !== null ? `${Math.round(item.share * 100)}%` : "—"}
            </span>
          </div>
        ))}
      </div>

      <p className={s.note}>
        {accuracyLine(party.items)} 손님이 쓴 후기 기준이고, 이 자리가 속한 상권
        전체를 함께 본 값이라 같은 상권 안 다른 자리도 같게 나와요. 등급이나 추천
        순서에는 쓰지 않았어요.
      </p>
    </section>
  );
}
