import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import SectorFlowView from './SectorFlowView'

/*
 * 只关心 `series` 这个 prop 的引用身份，所以图表组件换成记录器：
 * 引用变了就说明下游 `useMemo(..., [series, timePoints])` 会重算整张图。
 */
const seriesProps = []

vi.mock('./IntradayChart', () => ({
  default: ({ series }) => {
    seriesProps.push(series)
    return <div>分时图：{series.map((item) => item.name).join('、')}</div>
  },
}))
vi.mock('./HistoryChart', () => ({
  default: ({ series }) => <div>多日图：{series.map((item) => item.name).join('、')}</div>,
}))

const dailyData = {
  trade_date: '2026-09-09',
  time_points: ['09:30', '09:45'],
  series: [
    { code: 'A', name: '流入甲', latest_net_inflow: 3.2, data: [1.1, 3.2] },
    { code: 'B', name: '流出乙', latest_net_inflow: -2.1, data: [-1.0, -2.1] },
  ],
}

function envelope(data, overrides = {}) {
  return {
    status: 'ok', business_date: '2026-09-09', stale: false, warnings: [], data, ...overrides,
  }
}

/* 注意必须是稳定引用：默认参数每次渲染都会新建对象，那等于在测"父级换了数据"。 */
const stableResponse = envelope(dailyData)

/* 一个能主动触发父级重渲染的壳：模拟"有别的 state 变了"这一类无关更新。 */
function Harness({ response = stableResponse }) {
  const [, setTick] = useState(0)
  return (
    <>
      {/* 只用来制造一次与数据无关的父级重渲染，所以不读计数值。 */}
      <button type="button" onClick={() => setTick((value) => value + 1)}>无关重渲染</button>
      <SectorFlowView
        phase="ready"
        envelope={response}
        date=""
        days={1}
        onDateChange={() => {}}
        onWindowChange={() => {}}
        errorMessage="开盘啦数据暂时无法加载。"
      />
    </>
  )
}

describe('SectorFlowView', () => {
  it('keeps the date and window controls mounted in every data state', () => {
    render(
      <SectorFlowView
        phase="loading"
        envelope={null}
        date=""
        days={1}
        onDateChange={() => {}}
        onWindowChange={() => {}}
        errorMessage="开盘啦数据暂时无法加载。"
      />,
    )

    expect(screen.getByLabelText('数据日期')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '当日' })).toHaveAttribute('aria-pressed', 'true')
  })

  /*
   * 图表用 `useMemo(..., [series, ...])` 生成 ECharts option。`selectedSeries`
   * 若在渲染里内联 `.filter()`，每轮渲染都是新数组，任何无关的父级重渲染都会
   * 触发整图重算 + setOption。这里锁住"无关重渲染不换 series 引用"。
   */
  it('keeps the selected series identity stable across unrelated re-renders', () => {
    seriesProps.length = 0
    render(<Harness />)

    // 首次渲染时"选中集合"还是空的（业务日期 effect 之后才填默认前 5 名）。
    expect(screen.getByText(/^分时图：/)).toBeInTheDocument()
    const first = seriesProps.at(-1)

    fireEvent.click(screen.getByRole('button', { name: '无关重渲染' }))

    expect(seriesProps.at(-1)).toBe(first)
  })

  it('recomputes the series when the selection actually changes', () => {
    seriesProps.length = 0
    render(<Harness />)

    const before = seriesProps.at(-1)
    fireEvent.click(screen.getByRole('checkbox', { name: /流入甲/ }))

    expect(seriesProps.at(-1)).not.toBe(before)
  })

  it('serves a syncing dataset as preparing without dropping the controls', async () => {
    render(
      <SectorFlowView
        phase="ready"
        envelope={envelope(null, { status: 'error', error: { code: 'SYNC_IN_PROGRESS' } })}
        date=""
        days={1}
        onDateChange={() => {}}
        onWindowChange={() => {}}
        errorMessage="开盘啦数据暂时无法加载。"
      />,
    )

    expect(screen.getByText('数据准备中，请稍后刷新。')).toBeInTheDocument()
    expect(screen.getByLabelText('数据日期')).toBeInTheDocument()
    expect(screen.queryByText(/^分时图：/)).not.toBeInTheDocument()
  })
})
