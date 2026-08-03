import { MAX_MONEY, parseNum } from "../lib/guard";

// 카드마다 복제되어 있던 숫자 입력 한 벌. 스타일은 각 카드의 CSS 모듈
// (.field / .fieldLabel / .fieldInput / .unit / .req)을 그대로 받아 시각은
// 카드가 정하고, 값 검증(NaN·Infinity 거부, 범위 클램프)은 여기 한 곳이 정한다.

export default function NumField({
  s,
  label,
  value,
  onChange,
  unit = "만원",
  placeholder,
  required,
  min = 0,
  max = MAX_MONEY,
}: {
  /** 카드의 CSS 모듈 — 필드 클래스 이름 규약을 공유한다 */
  s: Record<string, string>;
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  unit?: string;
  placeholder?: string;
  required?: boolean;
  min?: number;
  max?: number;
}) {
  return (
    <label className={s.field}>
      <span className={s.fieldLabel}>
        {label}
        {required ? <i className={s.req}>필수</i> : null}
      </span>
      <span className={s.fieldInput}>
        <input
          type="number"
          min={min}
          max={max}
          value={value ?? ""}
          placeholder={placeholder}
          onChange={(e) => onChange(parseNum(e.target.value, { min, max }))}
        />
        <span className={s.unit}>{unit}</span>
      </span>
    </label>
  );
}
