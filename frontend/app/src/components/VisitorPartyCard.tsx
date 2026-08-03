import type { VisitorParty } from "../api/types";
import { int } from "../lib/format";
import s from "./VisitorPartyCard.module.css";

// 후기에서 «누구와 왔는지»가 적힌 것만 센 관측이다. 비율도 서버가 계산한 share
// 를 쓰고, 순위나 전망을 클라이언트에서 만들지 않는다.
//
// 정확도 문구(«10건 중 N건쯤 틀려요»)는 소유자 판단으로 뺐다(2026-08-01). 코퍼스
// 일부를 다른 추출기로 라벨하기로 하면서 §J-1 의 0.633·0.700 이 화면 전체를
// 설명하지 못하게 됐고, 맞지 않는 수치를 남기느니 수치를 안 내는 쪽을 골랐다.
// `precision` 은 응답에 그대로 실려 있으므로 되살릴 때 API 변경은 필요 없다.

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
        {/* «누구와 왔는지 적힌 N개»는 거짓이었다 — labelled 는 서빙하는 두
            클래스의 합이고, 혼자·친구·연인으로 적힌 글은 분모 밖이다. */}
        <p>
          이 상권 후기 {int(party.postsScanned)}개에서 가족·회식 표현이 확인된{" "}
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
              {item.share !== null ? `${Math.round(item.share * 100)}%` : "-"}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
