import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import HundredDayPage from './HundredDayPage'

vi.mock('./RatioTrendChart', () => ({
  default: ({ trend }) => <div>占比趋势：{trend.map((point) => point.trade_date).join('、')}</div>,
}))

function envelope(data, overrides = {}) {
  return {
    status: 'ok', business_date: '2026-09-09', data_version: 'hundred-day:1',
    stale: false, warnings: [], data, ...overrides,
  }
}

const result = {
  trade_date: '2026-09-09',
  totals: {
    valid_stock_count: 10, new_high_count: 2, new_low_count: 1,
    new_high_ratio: '0.2', new_low_ratio: '0.1',
  },
  industry_summaries: [
    {
      industry_code: 'P01', industry_name: '父行业甲', stock_count: 3,
      new_high_count: 2, new_low_count: 0,
      new_high_stocks: [{ code: '600001', name: '新高股票' }], new_low_stocks: [],
    },
    {
      industry_code: 'P02', industry_name: '父行业乙', stock_count: 2,
      new_high_count: 0, new_low_count: 1,
      new_high_stocks: [], new_low_stocks: [{ code: '000001', name: '新低股票' }],
    },
  ],
  trend: [
    { trade_date: '2026-09-08', valid_stock_count: 8, new_high_count: 1, new_low_count: 2, new_high_ratio: '0.125', new_low_ratio: '0.25' },
    { trade_date: '2026-09-09', valid_stock_count: 10, new_high_count: 2, new_low_count: 1, new_high_ratio: '0.2', new_low_ratio: '0.1' },
  ],
}

describe('HundredDayPage', () => {
  it('renders totals, structured trend, separate parent-industry rankings, and collapsed stock details', async () => {
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(result)) }
    render(<HundredDayPage apiClient={apiClient} />)

    expect(await screen.findByText('有效股票：10 只')).toBeInTheDocument()
    expect(screen.getByText('新高：2 只（20.00%）')).toBeInTheDocument()
    expect(screen.getByText('新低：1 只（10.00%）')).toBeInTheDocument()
    expect(screen.getByText('占比趋势：2026-09-08、2026-09-09')).toBeInTheDocument()
    expect(screen.getByText('父行业甲（2）')).toBeInTheDocument()
    expect(screen.getByText('父行业乙（1）')).toBeInTheDocument()
    expect(screen.queryByText(/新高股票/)).not.toBeInTheDocument()

    const highRanking = screen.getByRole('region', { name: '新高行业排行' })
    fireEvent.click(within(highRanking).getByRole('button', { name: '展开股票明细' }))
    expect(screen.getByText(/新高股票/)).toBeInTheDocument()
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/hundred-day/', expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('uses a date-specific local API request and keeps empty rankings independent', async () => {
    const empty = { ...result, industry_summaries: [] }
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(empty)) }
    render(<HundredDayPage apiClient={apiClient} />)

    expect(await screen.findByText('暂无新高行业排行')).toBeInTheDocument()
    expect(screen.getByText('暂无新低行业排行')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('数据日期'), { target: { value: '2026-09-08' } })
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/hundred-day/?date=2026-09-08', expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it.each([
    ['preparing', envelope(null, { status: 'error', error: { code: 'DATA_PREPARING' } }), '数据准备中，请稍后刷新。'],
    ['insufficient history', envelope(null, { status: 'error', error: { code: 'INSUFFICIENT_HISTORY' } }), '历史数据不足，无法计算百日指标'],
    ['stale', envelope(result, { stale: true }), '正在展示旧数据'],
  ])('shows the %s state', async (_name, response, text) => {
    render(<HundredDayPage apiClient={{ request: vi.fn().mockResolvedValue(response) }} />)
    expect(await screen.findByText(text)).toBeInTheDocument()
  })
})
