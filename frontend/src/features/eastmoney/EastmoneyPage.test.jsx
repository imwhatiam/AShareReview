import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import EastmoneyPage from './EastmoneyPage'

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
    data_version: 'eastmoney:1',
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
    { trade_date: '2026-09-09', series: dailyData.series },
    { trade_date: '2026-09-08', series: [dailyData.series[0]] },
  ],
  period_rankings: {
    inflows: [{ code: 'A', name: '流入甲', net_inflow_total: 4.3 }],
    outflows: [{ code: 'B', name: '流出乙', net_inflow_total: -2.1 }],
  },
}

describe('EastmoneyPage', () => {
  it('loads the default local intraday endpoint and supports date and history window changes', async () => {
    const apiClient = {
      request: vi.fn((path) => Promise.resolve(
        path.includes('/history/') ? envelope(historyData) : envelope(dailyData),
      )),
    }
    render(<EastmoneyPage apiClient={apiClient} />)

    expect(await screen.findByText('分时图：流入甲、流出乙')).toBeInTheDocument()
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/eastmoney/sectors/intraday/?inflow_top=25&outflow_top=25',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )

    fireEvent.click(screen.getByRole('button', { name: '5日' }))
    expect(await screen.findByText('多日图：流入甲、流出乙')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('数据日期'), { target: { value: '2026-09-08' } })
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/eastmoney/sectors/intraday/history/?date=2026-09-08&days=5&inflow_top=25&outflow_top=25',
      expect.any(Object),
    )
  })

  it.each([
    ['preparing', envelope(null, {
      status: 'error', error: { code: 'DATA_PREPARING' },
    }), '数据准备中，请稍后刷新。'],
    ['unavailable', envelope(null, {
      status: 'error', error: { code: 'DATA_NOT_AVAILABLE' },
    }), '暂无数据'],
  ])('shows the accepted %s upstream state without pretending chart data exists', async (_name, response, message) => {
    const apiClient = { request: vi.fn().mockResolvedValue(response) }
    render(<EastmoneyPage apiClient={apiClient} />)

    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(screen.queryByText(/分时图：/)).not.toBeInTheDocument()
  })

  it('turns a local DATA_NOT_AVAILABLE API error into an empty Eastmoney state', async () => {
    const apiClient = {
      request: vi.fn().mockRejectedValue(Object.assign(new Error('not available'), {
        code: 'DATA_NOT_AVAILABLE',
        envelope: envelope(null, {
          status: 'error', error: { code: 'DATA_NOT_AVAILABLE' },
        }),
      })),
    }
    render(<EastmoneyPage apiClient={apiClient} />)

    expect(await screen.findByText('暂无数据')).toBeInTheDocument()
  })

  it('labels one-sided data as partial, names the missing direction, and retains stale data context', async () => {
    const apiClient = {
      request: vi.fn().mockResolvedValue(envelope({
        ...dailyData,
        series: [dailyData.series[0]],
        missing_directions: ['outflow'],
      }, {
        status: 'partial',
        stale: true,
        warnings: [
          '东方财富资金流缺少流出榜数据。',
          '东方财富上游数据暂不可用，正在展示最近可用数据。',
        ],
      })),
    }
    render(<EastmoneyPage apiClient={apiClient} />)

    expect(await screen.findByText('分时图：流入甲')).toBeInTheDocument()
    expect(screen.getByText('部分数据')).toBeInTheDocument()
    expect(screen.getByText('正在展示旧数据')).toBeInTheDocument()
    expect(screen.getByText('东方财富资金流缺少流出榜数据。')).toBeInTheDocument()
  })

  it('isolates a local API request failure to the Eastmoney content area', async () => {
    const apiClient = { request: vi.fn().mockRejectedValue(new Error('network')) }
    render(<EastmoneyPage apiClient={apiClient} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('东方财富数据暂时无法加载。')
  })
})
