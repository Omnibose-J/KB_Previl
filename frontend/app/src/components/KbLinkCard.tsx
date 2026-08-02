import s from "./KbLinkCard.module.css";

// KB 연계 — 이 자리 진단을 KB 창구로 넘긴다.
//
// 무엇이 뜨는지는 **승계 확률 하나**가 정한다. 계약 여부는 묻지 않는다 —
// 우리는 사용자가 계약했는지 모르고, 물어서 얻을 것도 없다.
//
// 승계 확률은 «다음 사람이 이어받을 가능성» 이지 권리금을 돌려받는 비율이
// 아니다(지불비율 원천 미확보). 그래서 카드는 금액을 말하지 않는다.

/** 실측 사다리에서 값이 가장 크게 뛰는 자리. M2 가 내는 서로 다른 값은 10개뿐이고
 *  그중 최댓값 0.3578 한 점에 전체의 39.0% 가 몰려 있다. 그 아래 계단은 0.160
 *  이라 사이가 비어 있어, 0.3 은 어느 쪽 덩어리도 가르지 않는 선이다. */
const SUCCESSION_STRONG = 0.3;

const LOAN_URL = "https://obank.kbstar.com/quics?page=C103425";
const CONSULTING_URL = "https://obiz.kbstar.com/quics?page=C044463";
const INSURANCE_URL = "https://obiz.kbstar.com/quics?page=C064555";

/** 권리금보호보험 가입 창. 놓치면 되돌릴 수 없는 기한이라 설명 문장에 섞지
 *  않고 따로 낸다 — 문장 안에 넣으면 읽는 사람이 «나중에 알아보지» 로 넘긴다. */
const INSURANCE_WINDOW = "계약 후 6개월 이내에만 가입할 수 있어요";

function Item({
  tag,
  title,
  desc,
  href,
  tone,
  note,
}: {
  tag: string;
  title: string;
  desc: string;
  href: string;
  tone?: "accent";
  note?: string;
}) {
  return (
    <a
      className={tone === "accent" ? s.accent : s.item}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      <span className={s.tag}>{tag}</span>
      <strong>{title}</strong>
      <p>{desc}</p>
      {note ? <span className={s.note}>{note}</span> : null}
    </a>
  );
}

export default function KbLinkCard({ successionProb }: { successionProb: number | null }) {
  // 값이 없으면 어느 쪽 문장도 참이 아니다. 한쪽을 골라 두는 것이 곧 «이 자리는
  // 안전하다/위험하다» 를 근거 없이 말하는 것이라, 카드를 통째로 내지 않는다.
  if (successionProb === null) return null;
  const strong = successionProb >= SUCCESSION_STRONG;

  return (
    <section className={s.card} data-reveal>
      <div className={s.head}>
        <h2>KB와 이어서 하기</h2>
        <p>
          {strong
            ? "이 자리는 다음 사람이 이어받은 기록이 비교적 많아요."
            : "이 자리는 다음 사람이 이어받은 기록이 적어요."}
        </p>
      </div>

      {/* 보험이 맨 앞이다. 권리금은 이 서비스가 다루는 돈 중 유일하게 «못 건질
          수도 있는» 몫이고, 승계가 적은 자리일수록 그 위험이 실제로 크다. */}
      {strong ? (
        <Item
          tag="권리금보호보험"
          title="이 자리는 보험 필요성이 낮아 보여요"
          desc="이어받은 기록이 비교적 많은 자리예요. 참고용으로만 보셔도 돼요."
          href={INSURANCE_URL}
          note={INSURANCE_WINDOW}
        />
      ) : (
        <Item
          tone="accent"
          tag="권리금보호보험"
          title="권리금, 못 건질 수 있어요"
          desc="이어받은 기록이 적은 자리라 권리금 회수 위험이 커요. 보험으로 그 몫을 덮을 수 있어요."
          href={INSURANCE_URL}
          note={INSURANCE_WINDOW}
        />
      )}

      {strong ? (
        <Item
          tone="accent"
          tag="전문가 상담"
          title="이 리포트 그대로 상담까지"
          desc="입지 등급 · 권리금 밴드 · 실질 점유비용을 들고 KB 소상공인 컨설팅 상담을 받아보세요."
          href={CONSULTING_URL}
        />
      ) : (
        <Item
          tag="계약 전 점검"
          title="이 조건, 신중하게 검토하세요"
          desc="계약 전에 KB 소상공인 컨설팅 전문가와 한 번 점검해 보세요."
          href={CONSULTING_URL}
        />
      )}

      <Item
        tag="자금 계획"
        title="이 조건이면 얼마가 부족한지"
        desc="KB 소상공인 신용대출 · 보증서대출 · 정책자금대출"
        href={LOAN_URL}
      />

      <p className={s.foot}>
        승계 가능성은 그 자리에서 가게가 문을 닫은 뒤 다음 가게가 곧바로 들어온
        비율이에요. 권리금을 얼마나 돌려받는지는 아니에요.
      </p>
    </section>
  );
}
