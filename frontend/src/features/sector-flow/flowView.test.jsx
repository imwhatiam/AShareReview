import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { pickDate } from '../../test/datePicker'
import FlowControls from './FlowControls'
import HistoryChart from './HistoryChart'
import IntradayChart from './IntradayChart'
import RankingList, { getDefaultSelectedCodes } from './RankingList'

/*
 * 这三个 spy 必须在模块级声明：`vi.mock` 的工厂会被提升，只有模块级的变量才
 * 能被它引用。代价是它们的调用记录会跨用例累积（vitest 默认不自动清理），
 * 而"取最后一次调用"的写法（`.at(-1)`）恰好会把这种泄漏盖住 —— 上一条用例
 * 若留下了更晚的调用，断言读到的是别人的数据，用例照样绿。
 * 所以每条用例前显式清空，让"最后一次"确实指本条用例。
 */
const setOption = vi.fn()
const resize = vi.fn()
const dispose = vi.fn()

vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption, resize, dispose })),
}))

const inflows = Array.from({ length: 6 }, (_, index) => ({
  code: `I${index + 1}`,
  name: `流入行业${index + 1}`,
  latest_net_inflow: 6 - index,
}))
const outflows = Array.from({ length: 6 }, (_, index) => ({
  code: `O${index + 1}`,
  name: `流出行业${index + 1}`,
  latest_net_inflow: index - 6,
}))


describe('sector-flow shared controls and charts', () => {
  beforeEach(() => {
    setOption.mockClear()
    resize.mockClear()
    dispose.mockClear()
  })

  it('offers a date selector and the approved 1/5/10/20-day windows', () => {
    const onDateChange = vi.fn()
    const onWindowChange = vi.fn()
    render(
      <FlowControls
        date="2026-09-09"
        days={1}
        onDateChange={onDateChange}
        onWindowChange={onWindowChange}
      />,
    )

    pickDate('2026-09-08')
    fireEvent.click(screen.getByRole('button', { name: '10日' }))

    expect(onDateChange).toHaveBeenCalledWith('2026-09-08')
    expect(onWindowChange).toHaveBeenCalledWith(10)
    expect(screen.getByRole('button', { name: '当日' })).toHaveAttribute('aria-pressed', 'true')

    /*
     * 统计窗口那组分段按钮必须留着可访问名。四个按钮的文字是"当日/5日/10日/20日"，
     * 没有组名的话读屏念出来就是四个孤立的数字，听不出在选什么 —— 这也是
     * 唯一一条钉住这个名字的用例。
     */
    expect(screen.getByRole('group', { name: '统计窗口' })).toBeInTheDocument()
  })

  it('renders the controls inline without an extra bordered panel', () => {
    const { container } = render(
      <FlowControls
        date="2026-09-09"
        days={1}
        onDateChange={() => {}}
        onWindowChange={() => {}}
      />,
    )

    expect(container.querySelector('.panel')).toBeNull()
    expect(screen.getByRole('group', { name: '板块资金流筛选条件' })).toBeInTheDocument()
  })

  it('selects the first five inflow and outflow sectors by default and renders toggleable rankings', () => {
    const selectedCodes = getDefaultSelectedCodes(inflows, outflows)
    const onToggle = vi.fn()
    render(
      <RankingList
        direction="inflow"
        items={inflows}
        selectedCodes={selectedCodes}
        onToggle={onToggle}
      />,
    )

    expect(selectedCodes).toEqual(new Set([
      'I1', 'I2', 'I3', 'I4', 'I5', 'O1', 'O2', 'O3', 'O4', 'O5',
    ]))
    expect(screen.getAllByRole('checkbox')).toHaveLength(6)
    fireEvent.click(screen.getByRole('checkbox', { name: /流入行业6/ }))
    expect(onToggle).toHaveBeenCalledWith('I6')
  })

  it('caps each ranking list at the ten displayed sectors', () => {
    const items = Array.from({ length: 12 }, (_, index) => ({
      code: `I${index + 1}`,
      name: `候选行业${index + 1}`,
      latest_net_inflow: 12 - index,
    }))
    render(
      <RankingList
        direction="inflow"
        items={items}
        selectedCodes={new Set()}
        onToggle={() => {}}
      />,
    )

    expect(screen.getAllByRole('checkbox')).toHaveLength(10)
    expect(screen.queryByRole('checkbox', { name: /候选行业11/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /候选行业12/ })).not.toBeInTheDocument()
  })

  /*
   * 榜单行里的金额必须与折线右端标签逐字一致（下面那组字面量与"资金流图表"用例里的
   * 「流入行业1 +3.4亿」同源）：两处曾经各写一份 `formatAmount`，只差缺失值返回
   * `''` 还是 `'—'`，改一处不会有测试变红。现在写法共用 `stockFormat.formatFlowAmount`，
   * 这里锁住"榜单侧确实消费了它"——折线一侧由图表用例锁住。
   */
  it('writes the ranking money exactly like the chart end label, dashes when missing', () => {
    render(
      <RankingList
        direction="inflow"
        items={[
          { code: 'I1', name: '流入行业1', latest_net_inflow: 3.4 },
          { code: 'I2', name: '无数据行业', latest_net_inflow: null },
        ]}
        selectedCodes={new Set()}
        onToggle={() => {}}
      />,
    )

    expect(screen.getByText('+3.4亿')).toBeInTheDocument()
    // 缺失值：榜单单画破折号，折线端则退化成"只有板块名"。
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('passes null intraday points to ECharts without converting them to zero', async () => {
    render(
      <IntradayChart
        timePoints={['09:30', '09:45', '10:00']}
        series={[{
          code: 'I1', name: '流入行业1', latest_net_inflow: 1.2, data: [1.2, null, 3.4],
        }]}
      />,
    )

    await waitFor(() => expect(setOption).toHaveBeenCalled())
    const option = setOption.mock.calls.at(-1)[0]
    expect(option.xAxis.data).toEqual(['09:30', '09:45', '10:00'])
    expect(option.series[0].data).toEqual([1.2, null, 3.4])
  })

  it('renders structured multi-day series without turning missing values into zero', async () => {
    render(
      <HistoryChart
        timePoints={['09-08 15:00', '09-09 15:00']}
        series={[{
          code: 'O1', name: '流出行业1', latest_net_inflow: -2.2, data: [-1.2, null],
        }]}
      />,
    )

    await waitFor(() => expect(setOption).toHaveBeenCalled())
    const option = setOption.mock.calls.at(-1)[0]
    expect(option.xAxis.data).toEqual(['09-08 15:00', '09-09 15:00'])
    expect(option.series[0].data).toEqual([-1.2, null])
  })

  /*
   * 分时轴刻度必须落在"整十分钟"上：下午从 13:00 起、到 15:00 止。
   * 按索引等间隔抽稀会跨过午休错位一格（13:05 … 14:55），这里锁死时刻判断。
   */
  it('puts intraday axis ticks on clock ten-minute marks while keeping raw categories', async () => {
    const timePoints = ['11:30', '13:00', '13:05', '13:15', '15:00']
    render(
      <IntradayChart
        timePoints={timePoints}
        series={[{
          code: 'I1', name: '流入行业1', latest_net_inflow: 1.2, data: [1, 2, 3, 4, 5],
        }]}
      />,
    )

    await waitFor(() => expect(setOption).toHaveBeenCalled())
    const option = setOption.mock.calls.at(-1)[0]
    expect(option.xAxis.data).toEqual(timePoints)
    const { interval } = option.xAxis.axisLabel
    expect(timePoints.map((value, index) => interval(index, value)))
      .toEqual([true, true, false, false, true])
  })

  it('leaves the multi-day date axis on the shared auto interval', async () => {
    render(
      <HistoryChart
        timePoints={['09-08 15:00', '09-09 15:00']}
        series={[{
          code: 'O1', name: '流出行业1', latest_net_inflow: -2.2, data: [-1.2, -2.2],
        }]}
      />,
    )

    await waitFor(() => expect(setOption).toHaveBeenCalled())
    const option = setOption.mock.calls.at(-1)[0]
    expect(option.xAxis.axisLabel.interval).toBeUndefined()
  })

  /*
   * 顶部图例改为折线右端的常驻标签：板块名 + 带符号的净额（亿），
   * 并为标签预留右侧留白，避免被裁切。
   */
  it('replaces the top legend with a right-edge label carrying the sector and its net flow', async () => {
    render(
      <IntradayChart
        timePoints={['09:30', '09:40']}
        series={[{
          code: 'I1', name: '流入行业1', latest_net_inflow: 3.4, data: [1.2, 3.4],
        }]}
      />,
    )

    await waitFor(() => expect(setOption).toHaveBeenCalled())
    const option = setOption.mock.calls.at(-1)[0]
    expect(option.legend).toBeUndefined()

    const { endLabel } = option.series[0]
    expect(endLabel.show).toBe(true)
    /*
     * 标签画在 grid 右边界之外，可用宽度 = grid.right - endLabel.distance，
     * 不够就会被画布裁掉、等于丢掉板块名。实测最坏组合（7 个汉字板块名 +
     * 三位数亿级净额）约 146px，因此这里锁住留白不得小于该值。
     */
    expect(option.grid.right - endLabel.distance).toBeGreaterThanOrEqual(146)

    expect(endLabel.formatter({ value: 3.4, seriesName: '流入行业1' })).toBe('流入行业1 +3.4亿')
    expect(endLabel.formatter({ value: -2.1, seriesName: '流出行业2' })).toBe('流出行业2 -2.1亿')
    expect(endLabel.formatter({ value: null, seriesName: '无数据行业' })).toBe('无数据行业')
  })
})
