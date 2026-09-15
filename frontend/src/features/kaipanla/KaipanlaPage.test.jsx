import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { pickDate } from '../../test/datePicker'
import { DATA_UPDATED_AT, envelope } from '../../test/envelope'
import { expectRefreshRefetches } from '../../test/refreshStamp'
import KaipanlaPage from './KaipanlaPage'
import { buildKaipanlaPath } from './useKaipanlaData'

vi.mock('../sector-flow/IntradayChart', () => ({
  default: ({ series }) => <div>分时图：{series.map((item) => item.name).join('、')}</div>,
}))
vi.mock('../sector-flow/HistoryChart', () => ({
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
const historyData = {
  items: [
    { trade_date: '2026-09-09', series: [
      { code: 'A', name: '流入甲', latest_net_inflow: 3.2, data: [3.2] },
      { code: 'B', name: '流出乙', latest_net_inflow: -2.1, data: [-2.1] },
    ] },
    { trade_date: '2026-09-08', series: [
      { code: 'A', name: '流入甲', latest_net_inflow: 1.1, data: [1.1] },
    ] },
  ],
  period_rankings: {
    inflows: [{ code: 'A', name: '流入甲', net_inflow_total: 4.3 }],
    outflows: [{ code: 'B', name: '流出乙', net_inflow_total: -2.1 }],
  },
}


describe('KaipanlaPage', () => {
  it('loads the default intraday endpoint and renders the date, selections, and chart', async () => {
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(dailyData)) }
    render(<KaipanlaPage apiClient={apiClient} />)

    expect(await screen.findByText('分时图：流入甲、流出乙')).toBeInTheDocument()
    // 模块名与说明只在导航 Tab 上出现一次，页面内不再重复渲染区块标题/副标题。
    expect(screen.queryByText('开盘啦板块资金流')).not.toBeInTheDocument()
    expect(screen.queryByText('当日分时累计净额，默认对比流入与流出前 5 名板块')).not.toBeInTheDocument()
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/kaipanla/sectors/intraday/?inflow_top=25&outflow_top=25',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(screen.getByRole('checkbox', { name: /流入甲/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /流出乙/ })).toBeChecked()

    // 流入 / 流出双榜单位于折线图下方。
    const chart = document.querySelector('.flow-chart')
    const rankings = document.querySelector('.flow-rankings')
    expect(chart.compareDocumentPosition(rankings)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect(rankings.querySelectorAll('.ranking')).toHaveLength(2)
  })

  /*
   * 2026-09-15：默认勾选改成"每次取数后按该次榜单重算"（此前用 business_date 当闸门，
   * 同一天内一律保留旧勾选）。换窗口 / 换日期都会带回一份新响应，两条路都要重算 ——
   * 这里先手动取消一项，再断言它在换窗口之后回到勾选态。
   */
  it('switches dates and windows, re-deriving the default selections from each response', async () => {
    const apiClient = {
      request: vi.fn(async (path) => {
        if (path.includes('date=2026-09-08')) {
          return envelope(historyData, {
            business_date: '2026-09-08',
          })
        }
        if (path.includes('/history/')) return envelope(historyData)
        return envelope(dailyData)
      }),
    }
    render(<KaipanlaPage apiClient={apiClient} />)

    const inflow = await screen.findByRole('checkbox', { name: /流入甲/ })
    await waitFor(() => expect(inflow).toBeChecked())
    fireEvent.click(inflow)
    expect(inflow).not.toBeChecked()

    fireEvent.click(screen.getByRole('button', { name: '5日' }))
    expect(await screen.findByText('多日图：流入甲、流出乙')).toBeInTheDocument()
    // 5日榜单同样是"流入甲 + 流出乙"，重算后刚才手动取消的那一项回到勾选态。
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /流入甲/ })).toBeChecked())

    pickDate('2026-09-08')
    expect(await screen.findByText('多日图：流入甲、流出乙')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /流入甲/ })).toBeChecked()
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/kaipanla/sectors/intraday/history/?days=5&inflow_top=25&outflow_top=25',
      expect.any(Object),
    )
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/kaipanla/sectors/intraday/history/?date=2026-09-08&days=5&inflow_top=25&outflow_top=25',
      expect.any(Object),
    )
  })

  it('jumps back to the latest trading day when the daily window is picked again', async () => {
    const apiClient = {
      request: vi.fn(async (path) => {
        if (path.includes('date=2026-09-08')) {
          return envelope(historyData, {
            business_date: '2026-09-08',
          })
        }
        if (path.includes('/history/')) return envelope(historyData)
        return envelope(dailyData)
      }),
    }
    render(<KaipanlaPage apiClient={apiClient} />)

    await screen.findByText('分时图：流入甲、流出乙')
    // 未手选日期时，日期框显示后端返回的最近交易日，而不是留空。
    expect(screen.getByLabelText('数据日期')).toHaveTextContent('2026-09-09')

    fireEvent.click(screen.getByRole('button', { name: '5日' }))
    await screen.findByText('多日图：流入甲、流出乙')
    pickDate('2026-09-08')
    expect(screen.getByLabelText('数据日期')).toHaveTextContent('2026-09-08')

    fireEvent.click(screen.getByRole('button', { name: '当日' }))

    // 切回当日即回到最近交易日：请求不再携带手选日期，日期框同步回最新日期。
    await waitFor(() => expect(screen.getByLabelText('数据日期')).toHaveTextContent('2026-09-09'))
    expect(apiClient.request).toHaveBeenLastCalledWith(
      '/api/kaipanla/sectors/intraday/?inflow_top=25&outflow_top=25',
      expect.any(Object),
    )
    expect(await screen.findByText('分时图：流入甲、流出乙')).toBeInTheDocument()
  })

  it.each([['5日', 5], ['10日', 10], ['20日', 20]])(
    'anchors the %s window on the latest trading day even after a historical date was picked',
    async (label, days) => {
      const apiClient = {
        request: vi.fn(async (path) => {
          const picked = /date=(\d{4}-\d{2}-\d{2})/.exec(path)
          const data = path.includes('/history/') ? historyData : dailyData
          return envelope(data, picked ? { business_date: picked[1] } : {})
        }),
      }
      render(<KaipanlaPage apiClient={apiClient} />)

      await screen.findByText('分时图：流入甲、流出乙')

      fireEvent.click(screen.getByRole('button', { name: '10日' }))
      await screen.findByText('多日图：流入甲、流出乙')
      pickDate('2026-09-08')
      expect(screen.getByLabelText('数据日期')).toHaveTextContent('2026-09-08')

      // 再次点击窗口按钮即回到“以最近交易日为终点”的窗口，请求不再携带手选日期。
      fireEvent.click(screen.getByRole('button', { name: label }))

      expect(apiClient.request).toHaveBeenLastCalledWith(
        `/api/kaipanla/sectors/intraday/history/?days=${days}&inflow_top=25&outflow_top=25`,
        expect.any(Object),
      )
      await waitFor(() => expect(screen.getByLabelText('数据日期')).toHaveTextContent('2026-09-09'))
    },
  )

  it.each([
    ['preparing', envelope(null, {
      status: 'error', error: { code: 'DATA_PREPARING' },
    }), '数据准备中，请稍后刷新。'],
    ['empty', envelope({ ...dailyData, series: [] }), '暂无数据'],
  ])('renders the %s response state without pretending it has chart data', async (_name, response, message) => {
    const apiClient = { request: vi.fn().mockResolvedValue(response) }
    render(<KaipanlaPage apiClient={apiClient} />)

    expect(await screen.findByRole('status')).toHaveTextContent(message)
    expect(screen.queryByText(/分时图：/)).not.toBeInTheDocument()
    // 没有数据时只隐藏图表与榜单，日期和统计窗口控件必须保留。
    expect(screen.getByLabelText('数据日期')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '当日' })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('keeps the date and window controls when a window switch returns no data', async () => {
    const apiClient = {
      request: vi.fn(async (path) => (
        path.includes('/history/')
          ? envelope({ items: [], period_rankings: { inflows: [], outflows: [] } })
          : envelope(dailyData)
      )),
    }
    render(<KaipanlaPage apiClient={apiClient} />)

    expect(await screen.findByText('分时图：流入甲、流出乙')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '5日' }))

    expect(await screen.findByText('暂无数据')).toBeInTheDocument()
    expect(screen.queryByText(/多日图：/)).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByText('资金流入排行')).not.toBeInTheDocument()
    expect(screen.queryByText('资金流出排行')).not.toBeInTheDocument()
    expect(screen.getByLabelText('数据日期')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '5日' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('keeps the stale marker visible without the removed partial-data chip, and isolates a request failure', async () => {
    const staleClient = {
      request: vi.fn().mockResolvedValue(envelope(dailyData, {
        status: 'partial', stale: true, warnings: ['开盘啦数据延迟。'],
      })),
    }
    const { unmount } = render(<KaipanlaPage apiClient={staleClient} />)
    expect(await screen.findByText('正在展示旧数据')).toBeInTheDocument()
    expect(screen.queryByText('部分数据')).not.toBeInTheDocument()
    expect(screen.getByText('开盘啦数据延迟。')).toBeInTheDocument()
    unmount()

    const failedClient = { request: vi.fn().mockRejectedValue(new Error('network')) }
    render(<KaipanlaPage apiClient={failedClient} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('开盘啦数据暂时无法加载。')
  })

  it('re-requests the same URL when「更新于」is clicked', () =>
    expectRefreshRefetches(KaipanlaPage, {
      payload: dailyData,
      endpoint: buildKaipanlaPath({ date: '', days: 1 }),
    }))

  /*
   * 2026-09-15（用户报障）：点「更新于 HH:MM」刷新后，两张榜单的条目换成了新数据，但
   * 勾选还停在刷新前那批板块上 —— 旧勾选的板块一旦掉出新榜单，两个榜单的勾选框会全部
   * 空着、折线图也一条线都不画，看起来就是"榜单没刷新好"。
   *
   * 这里让第二次响应换掉整份板块集合（业务日期不变），断言刷新后勾选与折线图都落在新
   * 数据的默认前 5 名上，而不是留在旧板块上。
   */
  it('re-derives the default selections from the refreshed rankings', async () => {
    const refreshedData = {
      trade_date: '2026-09-09',
      time_points: ['09:30', '09:45'],
      series: [
        { code: 'C', name: '新贵丙', latest_net_inflow: 9.9, data: [1.0, 9.9] },
        { code: 'D', name: '新贵丁', latest_net_inflow: -8.8, data: [-1.0, -8.8] },
      ],
    }
    const apiClient = {
      request: vi.fn()
        .mockResolvedValueOnce(envelope(dailyData, { data_updated_at: DATA_UPDATED_AT }))
        .mockResolvedValueOnce(envelope(refreshedData, { data_updated_at: DATA_UPDATED_AT })),
    }
    render(<KaipanlaPage apiClient={apiClient} />)

    const staleCheckbox = await screen.findByRole('checkbox', { name: /流入甲/ })
    await waitFor(() => expect(staleCheckbox).toBeChecked())

    fireEvent.click(screen.getByRole('button', { name: /更新于 15:35/ }))

    /*
     * 折线图文案必须当同步点：它只有在"勾选已按新数据重算"之后才可能出现
     * （重算前 selectedCodes 还是旧板块，一条线都画不出来）。先等它，再断勾选框，
     * 否则断言可能落在"榜单已换新、勾选还没重算"的那一帧上，变成 flaky。
     */
    expect(await screen.findByText('分时图：新贵丙、新贵丁')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /新贵丙/ })).toBeChecked())
    expect(screen.getByRole('checkbox', { name: /新贵丁/ })).toBeChecked()
    // 旧板块已不在新榜单里，连同它的勾选框一起消失。
    expect(screen.queryByRole('checkbox', { name: /流入甲/ })).not.toBeInTheDocument()
  })
})
