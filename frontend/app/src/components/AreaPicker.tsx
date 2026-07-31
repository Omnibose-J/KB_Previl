import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Point } from "../api/types";
import Dropdown from "./Dropdown";
import s from "./AreaPicker.module.css";

// 100m 격자만 깔린 지도에서는 «지금 어디를 보고 있나»를 알 길이 없다. 동 이름으로
// 날아가게 해 준다 — 추천 범위(자치구 필터)는 건드리지 않고 지도만 옮긴다. 범위를
// 좁히는 조작은 S2 가 이미 하고 있어서, 여기서 또 좁히면 둘이 어긋난다.

export default function AreaPicker({
  onPick,
  dark = false,
}: {
  onPick: (center: Point) => void;
  /** 어두운 바 안에 놓을 때 */
  dark?: boolean;
}) {
  const areas = useQuery({
    queryKey: ["areas"],
    queryFn: api.areas,
    staleTime: Infinity, // 행정동 목록은 세션 안에서 바뀌지 않는다
  });
  const [name, setName] = useState<string | null>(null);

  const options = useMemo(
    () =>
      (areas.data?.items ?? []).map((a) => {
        const label = `${a.district} ${a.admDong}`;
        return { value: label, label };
      }),
    [areas.data],
  );

  return (
    <div className={dark ? s.pickDark : s.pick}>
      <Dropdown
        compact
        dark={dark}
        searchable
        options={options}
        value={name}
        placeholder="지역 찾기"
        searchPlaceholder="동 이름으로 찾기"
        emptyNote={areas.isError ? "목록을 불러오지 못했습니다" : "불러오는 중…"}
        onSelect={(value) => {
          const hit = areas.data?.items.find(
            (a) => `${a.district} ${a.admDong}` === value,
          );
          if (!hit) return;
          setName(value);
          // 항상 새 배열로 넘긴다. 같은 좌표를 같은 참조로 다시 넣으면 지도의
          // flyTo 이펙트가 돌지 않아, 손으로 옮긴 뒤 같은 동을 다시 골라도
          // 되돌아오지 않는다.
          onPick([hit.center[0], hit.center[1]]);
        }}
      />
    </div>
  );
}
