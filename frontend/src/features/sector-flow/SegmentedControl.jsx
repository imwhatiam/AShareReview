/*
 * 分段按钮组：一组互斥的单选按钮（资金流页用它切统计窗口）。
 *
 * 归在 feature 目录而不是 `shared/ui/`：目前只有板块资金流的 `FlowControls.jsx`
 * 消费它。共享层只放被两个以上模块用的件 —— 等到第二个模块也需要互斥单选
 * （且用法一致）时再提回 `shared/ui/`，不必现在就替未来预留位置。
 */
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
