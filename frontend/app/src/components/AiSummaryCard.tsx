import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "../api/client";
import { ErrorState, Loading } from "./states";
import s from "./AiSummaryCard.module.css";

// 숫자는 서버가 계산하고 LLM 은 문장만 만든다. 그래서 입력이 자리와 업종뿐이고,
// 받은 값을 화면에서 문장에 끼워 넣지 않는다 — 그러면 화면이 계산에 참여하게 된다.
//
// 실패하면 실패로 그린다. 요약이 비는 것보다 지어낸 요약이 나쁘다.

export default function AiSummaryCard({
  gridId,
  uptae,
  active,
}: {
  gridId: string;
  uptae: string;
  /** 탭이 열렸을 때만 부른다. 패널은 숨겨져도 마운트돼 있어서, 이걸 안 걸면
   *  상세를 열 때마다 읽지도 않을 요약에 LLM 호출이 나간다. */
  active: boolean;
}) {
  const q = useQuery({
    queryKey: ["report", gridId, uptae],
    queryFn: () => api.report(gridId, uptae),
    enabled: active,
    retry: 0,
    staleTime: Infinity, // 같은 자리를 다시 열어도 다시 만들지 않는다
  });

  return (
    <section className={s.card} data-reveal>
      {/* 부제 없음 — 문장 아래 각주가 «아래 기록에서 그대로 가져왔다»를 더
          정확하게 말한다. 같은 말을 위아래에 두 번 두지 않는다. */}
      <div className={s.head}>
        <h2>AI는 이 자리를 이렇게 요약했어요</h2>
      </div>

      {q.isPending ? <Loading label="요약을 만드는 중이에요…" /> : null}

      {q.isError ? (
        <ErrorState
          onRetry={() => q.refetch()}
          // 503 은 «LLM 이 지금 안 된다» 이고 나머지는 다른 사유다. 뭉뚱그리면
          // 사용자가 다시 눌러야 할지 포기해야 할지 알 수 없다.
          detail={
            q.error instanceof ApiError && q.error.status === 503
              ? "요약 생성이 지금 막혀 있어요. 아래 기록은 그대로 보실 수 있어요."
              : undefined
          }
        />
      ) : null}

      {q.data ? (
        <>
          <ol className={s.lines}>
            {q.data.sentences.map((line, i) => (
              <li key={i} className={s.line}>
                {line}
              </li>
            ))}
          </ol>
          <p className={s.note}>
            숫자는 아래 기록에서 그대로 가져왔고, 문장으로 옮기는 일만 AI가 했어요.
          </p>
        </>
      ) : null}
    </section>
  );
}
