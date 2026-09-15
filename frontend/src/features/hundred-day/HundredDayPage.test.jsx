import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { pickDate } from '../../test/datePicker'
import { envelope } from '../../test/envelope'
import { expectRefreshRefetches } from '../../test/refreshStamp'
import HundredDayPage from './HundredDayPage'

vi.mock('./RatioTrendChart', () => ({
  default: ({ trend }) => <div>占比趋势：{trend.map((point) => point.trade_date).join('、')}</div>,
}))

const result = {
  trade_date: '2026-09-09',
  totals: {
    valid_stock_count: 10, new_high_count: 2, new_low_count: 1,
    new_high_ratio: '0.2', new_low_ratio: '0.1',
  },
  industry_summaries: [
    {
      industry_code: 'P01', industry_name: '板块甲', stock_count: 3,
      new_high_count: 2, new_low_count: 0,
      new_high_stocks: [{
        code: '600001', name: '新高股票', change_percent: '10', turnover: '123000000',
      }],
      new_low_stocks: [],
    },
    {
      industry_code: 'P02', industry_name: '板块乙', stock_count: 2,
      new_high_count: 0, new_low_count: 1,
      new_high_stocks: [],
      new_low_stocks: [{
        code: '000001', name: '新低股票', change_percent: '-6.5', turnover: '80000000',
      }],
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
    // 未手选日期时也要显示后端返回的业务日期，而不是占位文案。
    expect(screen.getByLabelText('数据日期')).toHaveTextContent('2026-09-09')
    expect(screen.getByLabelText('数据日期')).not.toHaveTextContent('最新交易日')
    // 模块名与说明只在导航 Tab 上出现一次，页面内不再重复渲染区块标题/副标题。
    expect(screen.queryByText('百日新高新低占比')).not.toBeInTheDocument()
    expect(screen.queryByText('按开盘啦板块统计近百日创新高 / 创新低的个股分布')).not.toBeInTheDocument()
    expect(screen.getByText('新高：2 只（20.00%）')).toBeInTheDocument()
    expect(screen.getByText('新低：1 只（10.00%）')).toBeInTheDocument()
    expect(screen.getByText('占比趋势：2026-09-08、2026-09-09')).toBeInTheDocument()
    expect(screen.getByText('板块甲（2）')).toBeInTheDocument()
    expect(screen.getByText('板块乙（1）')).toBeInTheDocument()
    expect(screen.queryByText(/新高股票/)).not.toBeInTheDocument()

    // 两个排行并排在同一行，方便左右对照。
    const grid = screen.getByRole('region', { name: '新高行业排行' }).parentElement
    expect(grid).toHaveClass('pair-grid')
    expect(grid.children).toHaveLength(2)

    const highRanking = screen.getByRole('region', { name: '新高行业排行' })
    fireEvent.click(within(highRanking).getByRole('button', { name: '展开股票明细' }))
    // 一行列出整只股票：名称（涨幅，成交额）；不再显示代码，也不再一只占一行。
    expect(within(highRanking).getByText('新高股票（+10.00%，1.23亿）')).toBeInTheDocument()
    expect(within(highRanking).queryByText('600001')).not.toBeInTheDocument()
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/hundred-day/', expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('lists at most ten industries per ranking', async () => {
    const many = {
      ...result,
      industry_summaries: Array.from({ length: 12 }, (_value, index) => ({
        industry_code: `P${String(index + 1).padStart(2, '0')}`,
        industry_name: `板块${index + 1}`,
        stock_count: 30 - index,
        new_high_count: 30 - index,
        new_low_count: 0,
        new_high_stocks: [],
        new_low_stocks: [],
      })),
    }
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(many)) }
    render(<HundredDayPage apiClient={apiClient} />)

    const highRanking = await screen.findByRole('region', { name: '新高行业排行' })
    expect(within(highRanking).getAllByRole('listitem')).toHaveLength(10)
    expect(within(highRanking).getByText('板块1（30）')).toBeInTheDocument()
    expect(within(highRanking).queryByText('板块11（20）')).not.toBeInTheDocument()
  })

  it('sorts the expanded stock details by change percent descending', async () => {
    const unsorted = {
      ...result,
      industry_summaries: [{
        industry_code: 'P01', industry_name: '板块甲', stock_count: 4,
        new_high_count: 4, new_low_count: 0,
        new_high_stocks: [
          { code: '600003', name: '中涨股', change_percent: '3.2', turnover: '100000000' },
          { code: '600001', name: '最高股', change_percent: '9.8', turnover: '200000000' },
          // 当日没有行情（例如停牌）：排最后，但不能被排序丢掉。
          { code: '600004', name: '停牌股', change_percent: null, turnover: null },
          { code: '600002', name: '小涨股', change_percent: '0.5', turnover: '300000000' },
        ],
        new_low_stocks: [],
      }],
    }
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(unsorted)) }
    render(<HundredDayPage apiClient={apiClient} />)

    const ranking = await screen.findByRole('region', { name: '新高行业排行' })
    fireEvent.click(within(ranking).getByRole('button', { name: '展开股票明细' }))

    const detail = within(ranking).getByRole('list', { name: '板块甲新高行业排行股票明细' })
    expect(within(detail).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      '最高股（+9.80%，2.00亿）',
      '中涨股（+3.20%，1.00亿）',
      '小涨股（+0.50%，3.00亿）',
      '停牌股（—，—）',
    ])
  })

  it('puts the date control and the three totals on one centered row', async () => {
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(result)) }
    render(<HundredDayPage apiClient={apiClient} />)

    const toolbar = (await screen.findByLabelText('数据日期')).closest('.toolbar')
    const stats = [...toolbar.querySelectorAll('.stat-row')]

    // 日期与三个汇总指标同处一行；排行条目里的"有效股票"不在这一行内。
    expect(toolbar.querySelector('.date-picker')).not.toBeNull()
    expect(stats.map((item) => item.textContent)).toEqual([
      '有效股票：10 只',
      '新高：2 只（20.00%）',
      '新低：1 只（10.00%）',
    ])
    expect(stats.every((item) => item.parentElement.classList.contains('stat-grid'))).toBe(true)
  })

  it('uses a date-specific local API request and keeps empty rankings independent', async () => {
    const empty = { ...result, industry_summaries: [] }
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(empty)) }
    render(<HundredDayPage apiClient={apiClient} />)

    expect(await screen.findByText('暂无新高行业排行')).toBeInTheDocument()
    expect(screen.getByText('暂无新低行业排行')).toBeInTheDocument()
    pickDate('2026-09-08')
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/hundred-day/?date=2026-09-08', expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it.each([
    ['preparing', envelope(null, { status: 'error', error: { code: 'DATA_PREPARING' } }), '数据准备中，请稍后刷新。'],
    ['syncing', envelope(null, { status: 'error', error: { code: 'SYNC_IN_PROGRESS' } }), '数据准备中，请稍后刷新。'],
    ['insufficient history', envelope(null, { status: 'error', error: { code: 'INSUFFICIENT_HISTORY' } }), '历史数据不足，无法计算百日指标'],
    ['stale', envelope(result, { stale: true }), '正在展示旧数据'],
  ])('shows the %s state', async (_name, response, text) => {
    render(<HundredDayPage apiClient={{ request: vi.fn().mockResolvedValue(response) }} />)
    expect(await screen.findByText(text)).toBeInTheDocument()
  })

  /*
   * 日期控件在任何数据状态下都必须保持挂载：`useResource` 在 path 变化时
   * 会把 phase 打回 loading，若页面据此整页替换，用户刚在弹层里点完一天，控件就被
   * 卸载重建 —— 弹层、焦点、滚动位置全丢，页面还会先塌成一行提示再弹回来。
   */
  it.each([
    ['loading', () => new Promise(() => {}), null],
    ['error', () => Promise.reject(new Error('network')), '百日新高新低数据暂时无法加载。'],
    ['syncing', () => Promise.resolve(envelope(null, { status: 'error', error: { code: 'SYNC_IN_PROGRESS' } })), '数据准备中，请稍后刷新。'],
    ['insufficient history', () => Promise.resolve(envelope(null, { status: 'error', error: { code: 'INSUFFICIENT_HISTORY' } })), '历史数据不足，无法计算百日指标'],
    ['empty', () => Promise.resolve(envelope(null, { status: 'error', error: { code: 'DATA_NOT_AVAILABLE' } })), '暂无数据'],
  ])('keeps the date control mounted while %s', async (_name, request, expectedText) => {
    render(<HundredDayPage apiClient={{ request: vi.fn(request) }} />)

    const dateTrigger = screen.getByLabelText('数据日期')
    expect(dateTrigger).toBeInTheDocument()
    if (expectedText) {
      expect(await screen.findByText(expectedText)).toBeInTheDocument()
      expect(screen.getByLabelText('数据日期')).toBeInTheDocument()
    }
    // 三个汇总指标依赖数据，没数据时整组不渲染（排行里的"有效股票"不在工具栏内）。
    expect(dateTrigger.closest('.toolbar').querySelectorAll('.stat-row')).toHaveLength(0)
  })

  /*
   * 该日期的汇总行没数据时也要把控件留住，而不是整页塌掉。
   */
  it('keeps the toolbar when the date has no totals', async () => {
    const apiClient = {
      request: vi.fn().mockResolvedValue(envelope({ ...result, totals: null })),
    }
    render(<HundredDayPage apiClient={apiClient} />)

    expect(await screen.findByText('板块甲（2）')).toBeInTheDocument()
    const dateTrigger = screen.getByLabelText('数据日期')
    expect(dateTrigger).toBeInTheDocument()
    // 三个汇总指标依赖 totals，缺失时整组不渲染（排行条目里的"有效股票"不在工具栏内）。
    expect(dateTrigger.closest('.toolbar').querySelectorAll('.stat-row')).toHaveLength(0)
  })

  it('re-requests the same day when「更新于」is clicked', () =>
    expectRefreshRefetches(HundredDayPage, { payload: result, endpoint: '/api/hundred-day/' }))
})
