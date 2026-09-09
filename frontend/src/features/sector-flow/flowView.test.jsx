import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import FlowControls from './FlowControls'
import HistoryChart from './HistoryChart'
import IntradayChart from './IntradayChart'
import RankingList, { getDefaultSelectedCodes } from './RankingList'

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

    fireEvent.change(screen.getByLabelText('数据日期'), { target: { value: '2026-09-08' } })
    fireEvent.click(screen.getByRole('button', { name: '10日' }))

    expect(onDateChange).toHaveBeenCalledWith('2026-09-08')
    expect(onWindowChange).toHaveBeenCalledWith(10)
    expect(screen.getByRole('button', { name: '当日' })).toHaveAttribute('aria-pressed', 'true')
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

  it('renders no more than the requested top 25 ranking candidates', () => {
    const items = Array.from({ length: 26 }, (_, index) => ({
      code: `I${index + 1}`,
      name: `候选行业${index + 1}`,
      latest_net_inflow: 26 - index,
    }))
    render(
      <RankingList
        direction="inflow"
        items={items}
        selectedCodes={new Set()}
        onToggle={() => {}}
      />,
    )

    expect(screen.getAllByRole('checkbox')).toHaveLength(25)
    expect(screen.queryByRole('checkbox', { name: /候选行业26/ })).not.toBeInTheDocument()
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
})
