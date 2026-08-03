import { man } from "../lib/format";
import s from "./KbLinkCard.module.css";

// KB 연계 — 이 자리 진단을 KB 창구로 넘긴다.
//
// 무엇이 뜨는지는 **승계 확률 하나**가 정한다. 계약 여부는 묻지 않는다 —
// 우리는 사용자가 계약했는지 모르고, 물어서 얻을 것도 없다.
//
// 순서(2026-08-03 사용자 지시, 기획 이미지 기준):
//   1. 점검/상담 — 계약 전 지금 당장 할 수 있는 일
//   2. 자금 계획 — 위 손익 카드가 계산한 부족액이 있으면 그 금액으로 말한다
//   3. 권리금보호보험 — 계약 후에만 가입 가능하므로 «미리 보기»로 맨 뒤, 회색
//
// 승계 확률은 «다음 사람이 이어받을 가능성» 이지 권리금을 돌려받는 비율이
// 아니다(지불비율 원천 미확보). 그래서 보험 카드는 금액을 말하지 않는다.

/** 실측 사다리에서 값이 가장 크게 뛰는 자리. M2 가 내는 서로 다른 값은 10개뿐이고
 *  그중 최댓값 0.3578 한 점에 전체의 39.0% 가 몰려 있다. 그 아래 계단은 0.160
 *  이라 사이가 비어 있어, 0.3 은 어느 쪽 덩어리도 가르지 않는 선이다. */
const SUCCESSION_STRONG = 0.3;

const LOAN_URL = "https://obank.kbstar.com/quics?page=C103425";
const CONSULTING_URL = "https://obiz.kbstar.com/quics?page=C044463";
const INSURANCE_URL = "https://obiz.kbstar.com/quics?page=C064555";

function Item({
  tag,
  title,
  desc,
  href,
  tone,
}: {
  tag: string;
  title: string;
  desc: string;
  href: string;
  tone?: "accent" | "preview";
}) {
  return (
    <a
      className={tone === "accent" ? s.accent : tone === "preview" ? s.preview : s.item}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      <span className={s.tag}>{tag}</span>
      <strong>{title}</strong>
      <p>{desc}</p>
    </a>
  );
}

export default function KbLinkCard({
  successionProb,
  shortfall,
}: {
  successionProb: number | null;
  /** 위 손익(runway) 카드가 계산한 운영자금 부족액(만원). 계산 전이면 null —
   *  그때 자금 계획 카드는 금액 없이 일반 문구로 말한다. 0 은 «부족 없음»이다. */
  shortfall?: number | null;
}) {
  // 값이 없으면 어느 쪽 문장도 참이 아니다. 한쪽을 골라 두는 것이 곧 «이 자리는
  // 안전하다/위험하다» 를 근거 없이 말하는 것이라, 카드를 통째로 내지 않는다.
  if (successionProb === null) return null;
  const strong = successionProb >= SUCCESSION_STRONG;
  const gap = shortfall ?? null;

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

      {/* 1. 지금 당장 할 수 있는 일 — 두 상태 모두 첫 카드가 강조다. */}
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
          tone="accent"
          tag="계약 전 반드시 점검"
          title="이 조건, 신중하게 검토하세요"
          desc="계약 전에 KB 소상공인 컨설팅 전문가와 한 번 점검해 보세요."
          href={CONSULTING_URL}
        />
      )}

      {/* 2. 자금 계획 — 위 손익 카드가 부족액을 이미 계산했다면 그 숫자로 말한다.
          계산 전엔 금액을 지어내지 않는다. */}
      <Item
        tag="자금 계획"
        title={
          gap === null
            ? "이 조건이면 얼마가 부족한지"
            : gap > 0
              ? `지금 조건이면 운영자금이 약 ${man(gap)} 부족해요`
              : "지금 조건이면 부족한 돈 없이 버텨져요"
        }
        desc={
          gap !== null && gap > 0
            ? "위 손익 계산의 초기 골짜기 기준이에요. KB 소상공인 신용대출 · 보증서대출 · 정책자금대출로 메울 수 있어요."
            : "KB 소상공인 신용대출 · 보증서대출 · 정책자금대출"
        }
        href={LOAN_URL}
      />

      {/* 3. 보험 — 계약 후 6개월 안에만 가입할 수 있어 지금은 «미리 보기»다.
          회색으로 눕혀 두되, 위험 신호가 있는 자리는 기한을 제목이 직접 말한다. */}
      {strong ? (
        <Item
          tone="preview"
          tag="권리금보호보험 · 미리 보기"
          title="이 자리는 보험 필요성이 낮아 보여요"
          desc="이어받은 기록이 비교적 많은 자리예요. 계약 후에도 참고용으로만 보셔도 돼요."
          href={INSURANCE_URL}
        />
      ) : (
        <Item
          tone="preview"
          tag="권리금보호보험 · 미리 보기"
          title="계약하시면 6개월간 가입할 수 있어요"
          desc="지금은 계약 전이라 가입할 수 없어요. 이 자리는 이어받은 기록이 적어서, 계약 후에 보험 가입을 특히 권해요."
          href={INSURANCE_URL}
        />
      )}

      <p className={s.foot}>
        승계 가능성은 그 자리에서 가게가 문을 닫은 뒤 다음 가게가 곧바로 들어온
        비율이에요. 권리금을 얼마나 돌려받는지는 아니에요.
      </p>
    </section>
  );
}
