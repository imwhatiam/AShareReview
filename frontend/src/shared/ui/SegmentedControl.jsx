/* 分段按钮组：用于互斥的单选切换（如统计窗口）。 */
export default function SegmentedControl({ legend, options, value, onChange }) {
  return (
    <div className="field">
      <div className="segmented" role="group" aria-label={legend}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className="segmented__item"
            aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  )
}
