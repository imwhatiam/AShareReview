import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { pickDate } from '../../test/datePicker'
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
  rank: 1, industry_code: 'P01', industry_name: '板块甲', stock_count: 2,
  average_change_percent: 7.5, industry_turnover: 300000000,
  market_turnover_ratio: 0.15, score: 2.25,
  stocks: [{ code: '600001', name: '样本股票', change_percent: 8, turnover: 100000000 }],
}
const results = {
  total_market_turnover: 2000000000,
  unmapped_stock_count: 1,
  rankings: { above_5pct: [ranking], top_5_percent: [{ ...ranking, industry_name: '板块乙' }] },
}

describe('SectorMomentumPage', () => {
  it('renders both ranking methods, score parts, structured charts, and collapsed stock details', async () => {
    /*
     * 故意喂入后端真实形态的响应（带 warnings + status=partial）：
     * 若页面又把告警/「部分数据」渲染回来，下面的否定断言会立刻失败。
     */
    const apiClient = {
      request: vi.fn().mockResolvedValue(envelope(results, {
        status: 'partial',
        warnings: ['1 只有效股票未映射到开盘啦板块。'],
      })),
    }
    render(<SectorMomentumPage apiClient={apiClient} />)

    expect(await screen.findByText('涨幅超过 5%')).toBeInTheDocument()
    // 未手选日期时也要显示后端返回的业务日期，而不是占位文案。
    expect(screen.getByLabelText('数据日期')).toHaveTextContent('2026-09-09')
    expect(screen.getByLabelText('数据日期')).not.toHaveTextContent('最新交易日')
    // 模块名与说明只在导航 Tab 上出现一次，页面内不再重复渲染区块标题/副标题。
    expect(screen.queryByText('板块动量')).not.toBeInTheDocument()
    expect(screen.queryByText('综合个股涨幅、成交活跃度与成交额占比的行业打分')).not.toBeInTheDocument()
    expect(screen.getByText('全市场涨幅前 5%')).toBeInTheDocument()
    expect(screen.getByText('动量图：板块甲')).toBeInTheDocument()
    expect(screen.getByText('动量图：板块乙')).toBeInTheDocument()
    expect(screen.getAllByText(/股票数：2/)).toHaveLength(2)
    expect(screen.getAllByText(/平均涨幅：7.50%/)).toHaveLength(2)
    expect(screen.getAllByText(/成交额占比：15.00%/)).toHaveLength(2)
    expect(screen.queryByText('样本股票')).not.toBeInTheDocument()

    // 两个口径并排在同一行，方便左右对照。
    const grid = screen.getByText('动量图：板块甲').closest('.panel').parentElement
    expect(grid).toHaveClass('pair-grid')
    expect(grid.children).toHaveLength(2)

    const aboveFiveSection = screen.getByRole('region', { name: '涨幅超过 5%' })
    fireEvent.click(within(aboveFiveSection).getByRole('button', { name: '展开股票明细' }))
    // 一行列出整只股票：名称（涨幅，成交额）；不再显示代码，也不再一只占一行。
    expect(within(aboveFiveSection).getByText('样本股票（+8.00%，1.00亿）')).toBeInTheDocument()
    expect(within(aboveFiveSection).queryByText('600001')).not.toBeInTheDocument()
    // 未映射行业的覆盖度说明不再打扰页面：数量仍留在接口数据里，只是不渲染。
    expect(screen.queryByText('1 只有效股票未映射到开盘啦板块。')).not.toBeInTheDocument()
    expect(screen.queryByText('部分数据')).not.toBeInTheDocument()
  })

  it('puts the date control and the market-turnover metric on one centered row', async () => {
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(results)) }
    render(<SectorMomentumPage apiClient={apiClient} />)

    const dateTrigger = await screen.findByLabelText('数据日期')
    const turnover = screen.getByText(/^全市场成交额：/)
    const dateField = dateTrigger.closest('.date-picker')

    expect(turnover.closest('.stat-grid').parentElement).toBe(dateField.parentElement)
    expect(dateField.parentElement).toHaveClass('toolbar')
  })

  it('uses a date-specific local API request and displays an empty ranking independently', async () => {
    const apiClient = { request: vi.fn().mockResolvedValue(envelope({ ...results, rankings: { above_5pct: [], top_5_percent: [] } })) }
    render(<SectorMomentumPage apiClient={apiClient} />)

    expect(await screen.findAllByText('暂无行业排行')).toHaveLength(2)
    pickDate('2026-09-08')
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/sector-momentum/?date=2026-09-08', expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it.each([
    ['preparing', envelope(null, { status: 'error', error: { code: 'DATA_PREPARING' } }), '数据准备中，请稍后刷新。'],
    ['syncing', envelope(null, { status: 'error', error: { code: 'SYNC_IN_PROGRESS' } }), '数据准备中，请稍后刷新。'],
    ['stale', envelope(results, { stale: true }), '正在展示旧数据'],
  ])('shows the %s state', async (_name, response, text) => {
    render(<SectorMomentumPage apiClient={{ request: vi.fn().mockResolvedValue(response) }} />)
    expect(await screen.findByText(text)).toBeInTheDocument()
  })

  /*
   * 日期控件在任何数据状态下都必须保持挂载：`usePolledResource` 在 path 变化时
   * 会把 phase 打回 loading，若页面据此整页替换，用户刚在弹层里点完一天，控件就被
   * 卸载重建 —— 弹层、焦点、滚动位置全丢，页面还会先塌成一行提示再弹回来。
   */
  it.each([
    ['loading', () => new Promise(() => {}), null],
    ['error', () => Promise.reject(new Error('network')), '板块动量数据暂时无法加载。'],
    ['syncing', () => Promise.resolve(envelope(null, { status: 'error', error: { code: 'SYNC_IN_PROGRESS' } })), '数据准备中，请稍后刷新。'],
    ['empty', () => Promise.resolve(envelope(null, { status: 'error', error: { code: 'DATA_NOT_AVAILABLE' } })), '暂无数据'],
  ])('keeps the date control mounted while %s', async (_name, request, expectedText) => {
    render(<SectorMomentumPage apiClient={{ request: vi.fn(request) }} />)

    expect(screen.getByLabelText('数据日期')).toBeInTheDocument()
    if (expectedText) {
      expect(await screen.findByText(expectedText)).toBeInTheDocument()
      expect(screen.getByLabelText('数据日期')).toBeInTheDocument()
    }
    // 成交额依赖数据，没数据时不渲染。
    expect(screen.queryByText(/^全市场成交额：/)).not.toBeInTheDocument()
  })
})
