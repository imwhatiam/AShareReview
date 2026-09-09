import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import StockMovesPage from './StockMovesPage'

function envelope(data, overrides = {}) {
  return {
    status: 'ok',
    business_date: '2026-09-09',
    data_version: 'stock-moves:1',
    stale: false,
    warnings: [],
    data,
    ...overrides,
  }
}

const results = {
  trade_date: '2026-09-09',
  group_counts: { sse_rise: 1, sse_fall: 0, szse_rise: 1, szse_fall: 0 },
  stock_codes: ['000001', '600001'],
  distinct_stock_count: 2,
  groups: {
    sse_rise: [{
      rank: 1, code: '600001', name: '上证上涨', change_percent: 9,
      turnover: 900000000,
      parent_industries: [{ code: 'P01', name: '父行业甲' }],
    }],
    sse_fall: [],
    szse_rise: [{
      rank: 1, code: '000001', name: '深证上涨', change_percent: 8,
      turnover: 800000000,
      parent_industries: [],
    }],
    szse_fall: [],
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('StockMovesPage', () => {
  it('renders the four group summaries and only parent-industry labels', async () => {
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(results)) }
    render(<StockMovesPage apiClient={apiClient} />)

    expect(await screen.findByText('上证上涨（1）')).toBeInTheDocument()
    expect(screen.getByText('上证下跌（0）')).toBeInTheDocument()
    expect(screen.getByText('深证上涨（1）')).toBeInTheDocument()
    expect(screen.getByText('深证下跌（0）')).toBeInTheDocument()
    expect(screen.getByText('父行业甲')).toBeInTheDocument()
    expect(screen.getAllByText('暂无符合条件的个股')).toHaveLength(2)
    expect(screen.getByText('全部去重股票：2 只')).toBeInTheDocument()
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/stock-moves/',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('loads the selected date and copies exactly the supplied distinct stock codes', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(results)) }
    render(<StockMovesPage apiClient={apiClient} />)

    await screen.findByText('上证上涨（1）')
    fireEvent.change(screen.getByLabelText('数据日期'), { target: { value: '2026-09-08' } })
    await waitFor(() => expect(apiClient.request).toHaveBeenCalledWith(
      '/api/stock-moves/?date=2026-09-08',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ))
    await screen.findByRole('button', { name: '复制全部' })

    fireEvent.click(screen.getByRole('button', { name: '复制全部' }))
    expect(writeText).toHaveBeenCalledWith('000001\n600001')
    expect(await screen.findByRole('status')).toHaveTextContent('已复制 2 只股票代码。')
  })

  it('does not show a false success message when clipboard copying fails', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(results)) }
    render(<StockMovesPage apiClient={apiClient} />)

    await screen.findByText('上证上涨（1）')
    fireEvent.click(screen.getByRole('button', { name: '复制全部' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('复制失败，请手动复制股票代码。')
    expect(screen.queryByText('已复制 2 只股票代码。')).not.toBeInTheDocument()
  })

  it.each([
    ['preparing', envelope(null, { status: 'error', error: { code: 'DATA_PREPARING' } }), '数据准备中，请稍后刷新。'],
    ['stale', envelope(results, { stale: true, warnings: ['公共日行情版本已更新，正在展示最近可用的分析结果。'] }), '正在展示旧数据'],
  ])('shows the %s data state', async (_name, response, expectedText) => {
    const apiClient = { request: vi.fn().mockResolvedValue(response) }
    render(<StockMovesPage apiClient={apiClient} />)

    expect(await screen.findByText(expectedText)).toBeInTheDocument()
  })
})
