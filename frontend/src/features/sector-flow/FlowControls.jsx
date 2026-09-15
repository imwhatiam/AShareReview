import DatePicker from '../../shared/ui/DatePicker'
import RefreshStamp from '../../shared/RefreshStamp'
import SegmentedControl from './SegmentedControl'

const WINDOWS = [1, 5, 10, 20]

/*
 * 板块资金流筛选条件：与其余三个模块保持一致，直接落在卡片内，
 * 不额外包一层带边框阴影的面板；可访问名通过 role="group" 保留。
 * 「更新于 HH:MM」跟在日期控件右侧，与另外三个页面的位置一致 —— 它同时是刷新入口，
 * 所以要把页面的 `onRefresh` 一路透传下来（视图 → 这里 → RefreshStamp）。
 */
export default function FlowControls({
  date,
  days,
  onDateChange,
  onWindowChange,
  updatedAt = null,
  onRefresh,
}) {
  return (
    <div className="toolbar" role="group" aria-label="板块资金流筛选条件">
      <DatePicker id="flow-date" value={date} onChange={onDateChange} />
      <RefreshStamp updatedAt={updatedAt} onRefresh={onRefresh} />
      <SegmentedControl
        legend="统计窗口"
        options={WINDOWS.map((windowDays) => ({
          value: windowDays,
          label: windowDays === 1 ? '当日' : `${windowDays}日`,
        }))}
        value={days}
        onChange={onWindowChange}
      />
    </div>
  )
}
