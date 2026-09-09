import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import SectorMomentumPage from './SectorMomentumPage'

vi.mock('./MomentumChart', () => ({
  default: ({ rankings }) => <div>动量图：{rankings.map((item) => item.industry_name).join('、')}</div>,
}))

function envelope(data, overrides = {}) {
  return {
    status: 'ok', business_date: '2026-09-09', data_version: 'prices:industries',
    stale: false, warnings: [], data, ...overrides,
  }
}

const ranking = {
  rank: 1, industry_code: 'P01', industry_name: '父行业甲', stock_count: 2,
  average_change_percent: 7.5, industry_turnover: 300000000,
  market_turnover_ratio: 0.15, score: 2.25,
  stocks: [{ code: '600001', name: '样本股票', change_percent: 8, turnover: 100000000 }],
}
const results = {
  total_market_turnover: 2000000000,
  unmapped_stock_count: 1,
  rankings: { above_5pct: [ranking], top_5_percent: [{ ...ranking, industry_name: '父行业乙' }] },
}

describe('SectorMomentumPage', () => {
  it('renders both ranking methods, score parts, structured charts, and collapsed stock details', async () => {
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(results)) }
    render(<SectorMomentumPage apiClient={apiClient} />)

    expect(await screen.findByText('涨幅超过 5%')).toBeInTheDocument()
    expect(screen.getByText('全市场涨幅前 5%')).toBeInTheDocument()
    expect(screen.getByText('动量图：父行业甲')).toBeInTheDocument()
    expect(screen.getByText('动量图：父行业乙')).toBeInTheDocument()
    expect(screen.getAllByText(/股票数：2/)).toHaveLength(2)
    expect(screen.getAllByText(/平均涨幅：7.50%/)).toHaveLength(2)
    expect(screen.getAllByText(/成交额占比：15.00%/)).toHaveLength(2)
    expect(screen.queryByText('样本股票')).not.toBeInTheDocument()

    const aboveFiveSection = screen.getByRole('region', { name: '涨幅超过 5%' })
    fireEvent.click(within(aboveFiveSection).getByRole('button', { name: '展开股票明细' }))
    expect(screen.getByText(/样本股票/)).toBeInTheDocument()
    expect(screen.getByText('1 只有效股票未映射到开盘啦父行业。')).toBeInTheDocument()
  })

  it('uses a date-specific local API request and displays an empty ranking independently', async () => {
    const apiClient = { request: vi.fn().mockResolvedValue(envelope({ ...results, rankings: { above_5pct: [], top_5_percent: [] } })) }
    render(<SectorMomentumPage apiClient={apiClient} />)

    expect(await screen.findAllByText('暂无行业排行')).toHaveLength(2)
    fireEvent.change(screen.getByLabelText('数据日期'), { target: { value: '2026-09-08' } })
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/sector-momentum/?date=2026-09-08', expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it.each([
    ['preparing', envelope(null, { status: 'error', error: { code: 'DATA_PREPARING' } }), '数据准备中，请稍后刷新。'],
    ['stale', envelope(results, { stale: true }), '正在展示旧数据'],
  ])('shows the %s state', async (_name, response, text) => {
    render(<SectorMomentumPage apiClient={{ request: vi.fn().mockResolvedValue(response) }} />)
    expect(await screen.findByText(text)).toBeInTheDocument()
  })
})
