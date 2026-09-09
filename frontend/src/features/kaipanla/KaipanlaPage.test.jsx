import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import KaipanlaPage from './KaipanlaPage'

vi.mock('../sector-flow/IntradayChart', () => ({
  default: ({ series }) => <div>分时图：{series.map((item) => item.name).join('、')}</div>,
}))
vi.mock('../sector-flow/HistoryChart', () => ({
  default: ({ series }) => <div>多日图：{series.map((item) => item.name).join('、')}</div>,
}))

function envelope(data, overrides = {}) {
  return {
    status: 'ok',
    business_date: '2026-09-09',
    data_version: 'kaipanla:1',
    stale: false,
    warnings: [],
    data,
    ...overrides,
  }
}

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
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/kaipanla/sectors/intraday/?inflow_top=25&outflow_top=25',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(screen.getByRole('checkbox', { name: /流入甲/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /流出乙/ })).toBeChecked()
  })

  it('switches dates and windows, retaining selections for the same business date but resetting on a new date', async () => {
    const apiClient = {
      request: vi.fn(async (path) => {
        if (path.includes('date=2026-09-08')) {
          return envelope(historyData, {
            business_date: '2026-09-08', data_version: 'kaipanla:2',
          })
        }
        if (path.includes('/history/')) return envelope(historyData)
        return envelope(dailyData)
      }),
    }
    render(<KaipanlaPage apiClient={apiClient} />)

    const inflow = await screen.findByRole('checkbox', { name: /流入甲/ })
    fireEvent.click(inflow)
    expect(inflow).not.toBeChecked()

    fireEvent.click(screen.getByRole('button', { name: '5日' }))
    expect(await screen.findByText('多日图：流出乙')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /流入甲/ })).not.toBeChecked()

    fireEvent.change(screen.getByLabelText('数据日期'), { target: { value: '2026-09-08' } })
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
  })

  it('keeps stale and partial source conditions visible, and isolates a request failure', async () => {
    const staleClient = {
      request: vi.fn().mockResolvedValue(envelope(dailyData, {
        status: 'partial', stale: true, warnings: ['开盘啦数据延迟。'],
      })),
    }
    const { unmount } = render(<KaipanlaPage apiClient={staleClient} />)
    expect(await screen.findByText('正在展示旧数据')).toBeInTheDocument()
    expect(screen.getByText('部分数据')).toBeInTheDocument()
    expect(screen.getByText('开盘啦数据延迟。')).toBeInTheDocument()
    unmount()

    const failedClient = { request: vi.fn().mockRejectedValue(new Error('network')) }
    render(<KaipanlaPage apiClient={failedClient} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('开盘啦数据暂时无法加载。')
  })
})
