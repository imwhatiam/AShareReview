const WINDOWS = [1, 5, 10, 20]

export default function FlowControls({ date, days, onDateChange, onWindowChange }) {
  return (
    <section aria-label="板块资金流筛选条件">
      <label htmlFor="flow-date">数据日期</label>
      <input
        id="flow-date"
        type="date"
        value={date}
        onChange={(event) => onDateChange(event.target.value)}
      />
      <div aria-label="统计窗口">
        {WINDOWS.map((windowDays) => (
          <button
            key={windowDays}
            type="button"
            aria-pressed={days === windowDays}
            onClick={() => onWindowChange(windowDays)}
          >
            {windowDays === 1 ? '当日' : `${windowDays}日`}
          </button>
        ))}
      </div>
    </section>
  )
}
