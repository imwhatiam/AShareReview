import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { pickDate } from '../../test/datePicker'
import { envelope } from '../../test/envelope'
import { expectRefreshRefetches } from '../../test/refreshStamp'
import StockMovesPage from './StockMovesPage'

const results = {
  trade_date: '2026-09-09',
  group_counts: {
    sse_rise: 1, sse_fall: 0,
    szse_rise: 1, szse_fall: 0,
    bse_rise: 0, bse_fall: 0,
  },
  // 后端按看板分组顺序返回（上证涨 → 深证涨），复制串直接消费它。
  stock_codes: ['600001', '000001'],
  distinct_stock_count: 2,
  groups: {
    sse_rise: [{
      rank: 1, code: '600001', name: '上证上涨', change_percent: 9,
      turnover: 900000000,
      industries: [{ code: 'P01', name: '板块甲' }],
    }],
    sse_fall: [],
    szse_rise: [{
      rank: 1, code: '000001', name: '深证上涨', change_percent: 8,
      turnover: 800000000,
      industries: [],
    }],
    szse_fall: [],
    bse_rise: [],
    bse_fall: [],
  },
}

// 北交所同样满足阈值，但不属于上证/深证：单独成行放在最后，且和沪深一样按方向拆成两栏。
const resultsWithBse = {
  ...results,
  group_counts: { ...results.group_counts, bse_rise: 1, bse_fall: 1 },
  stock_codes: ['600001', '000001', '920045', '920046'],
  distinct_stock_count: 4,
  groups: {
    ...results.groups,
    bse_rise: [{
      rank: 1, code: '920045', name: '蘅东光', change_percent: 9.81,
      turnover: 1218000000,
      industries: [{ code: 'P07', name: '通信' }, { code: 'P08', name: '电子' }],
    }],
    bse_fall: [{
      rank: 1, code: '920046', name: '蘅西光', change_percent: -8.42,
      turnover: 900000000,
      industries: [],
    }],
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('StockMovesPage', () => {
  it('renders the market-by-direction board and keeps stock codes off screen', async () => {
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(results)) }
    render(<StockMovesPage apiClient={apiClient} />)

    // 行 = 市场：上证 / 深证；北交所有数据才出现，这里不该渲染。
    expect(await screen.findByText('上证')).toBeInTheDocument()
    expect(screen.getByText('深证')).toBeInTheDocument()
    expect(screen.queryByText('北交所')).not.toBeInTheDocument()
    // 列 = 方向，用阈值说明做表头。
    expect(screen.getByText('涨幅超8% 成交超8亿')).toBeInTheDocument()
    expect(screen.getByText('跌幅超8% 成交超8亿')).toBeInTheDocument()

    const sseRise = screen.getByRole('region', { name: '上证上涨' })
    expect(sseRise).toHaveTextContent('上证上涨')
    expect(sseRise).toHaveTextContent('+9.00%')
    expect(sseRise).toHaveTextContent('9.00亿')

    // 股票代码不再上屏，开盘啦板块改由悬浮提示承载。
    expect(screen.queryByText('600001')).not.toBeInTheDocument()
    expect(screen.queryByText('000001')).not.toBeInTheDocument()
    expect(screen.getByTitle('板块：板块甲')).toBeInTheDocument()
    // 没有板块标签的股票也要给出提示，而不是留一个空白 title。
    expect(screen.getByTitle('板块：—')).toBeInTheDocument()

    // 空组整栏留白，不渲染占位文案；整页也不因此被视为失败。
    expect(screen.queryByText('暂无符合条件的个股')).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: '上证下跌' })).toBeEmptyDOMElement()
    expect(screen.getByRole('region', { name: '深证下跌' })).toBeEmptyDOMElement()

    const copyButton = screen.getByRole('button', { name: '共 2 只股票，全部复制' })
    // 复制是一个纯文字动作：无边框无底色，图标跟在"复制"后面而不是前面。
    expect(copyButton).toHaveClass('btn', 'btn--ghost')
    expect(copyButton).not.toHaveClass('btn--primary')
    expect(copyButton.textContent).toBe('共 2 只股票，全部复制')
    expect(copyButton.lastChild.tagName.toLowerCase()).toBe('svg')
    // 未手选日期时也要显示后端返回的业务日期，而不是占位文案。
    expect(screen.getByLabelText('数据日期')).toHaveTextContent('2026-09-09')
    expect(screen.getByLabelText('数据日期')).not.toHaveTextContent('最新交易日')
    expect(apiClient.request).toHaveBeenCalledWith(
      '/api/stock-moves/',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('loads the selected date and copies the codes comma separated in board order', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(results)) }
    render(<StockMovesPage apiClient={apiClient} />)

    await screen.findByText('上证')
    pickDate('2026-09-08')
    await waitFor(() => expect(apiClient.request).toHaveBeenCalledWith(
      '/api/stock-moves/?date=2026-09-08',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ))
    await screen.findByRole('button', { name: '共 2 只股票，全部复制' })

    fireEvent.click(screen.getByRole('button', { name: '共 2 只股票，全部复制' }))
    // 英文逗号分隔（不是换行），顺序与看板一致。
    expect(writeText).toHaveBeenCalledWith('600001,000001')
    expect(await screen.findByRole('status')).toHaveTextContent('已复制 2 只股票代码。')
  })

  it('splits Beijing stocks into their own rise and fall columns after the two exchanges', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(resultsWithBse)) }
    render(<StockMovesPage apiClient={apiClient} />)

    await screen.findByText('上证')
    // 不再用一条"已排除 N 只…"的告警替代这些股票，而是把它们列出来。
    expect(screen.queryByText(/已排除 .*北京证券交易所/)).not.toBeInTheDocument()

    const bseRise = screen.getByRole('region', { name: '北交所上涨' })
    expect(bseRise).toHaveTextContent('蘅东光')
    expect(bseRise).toHaveTextContent('+9.81%')
    expect(bseRise).toHaveTextContent('12.18亿')
    // 多个板块标签在同一个悬浮提示里并列。
    expect(screen.getByTitle('板块：通信、电子')).toBeInTheDocument()

    const bseFall = screen.getByRole('region', { name: '北交所下跌' })
    expect(bseFall).toHaveTextContent('蘅西光')
    expect(bseFall).toHaveTextContent('-8.42%')

    // 位置：整行排在深证之后。
    const szseFall = screen.getByRole('region', { name: '深证下跌' })
    expect(szseFall.compareDocumentPosition(bseRise) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '共 4 只股票，全部复制' }))
    expect(writeText).toHaveBeenCalledWith('600001,000001,920045,920046')
  })

  it('keeps the Beijing row when only one direction has stocks', async () => {
    // 2026-09-11 的真实形态：北交所有 1 只上涨、0 只下跌。
    const apiClient = {
      request: vi.fn().mockResolvedValue(envelope({
        ...results,
        group_counts: { ...results.group_counts, bse_rise: 1 },
        stock_codes: ['600001', '000001', '920045'],
        distinct_stock_count: 3,
        groups: {
          ...results.groups,
          bse_rise: [{
            rank: 1, code: '920045', name: '蘅东光', change_percent: 9.81,
            turnover: 1218000000,
            industries: [{ code: 'P07', name: '通信' }],
          }],
        },
      })),
    }
    render(<StockMovesPage apiClient={apiClient} />)

    await screen.findByText('上证')
    // 只有上涨侧有票时整行仍然保留，下跌侧留白。
    expect(screen.getByRole('region', { name: '北交所上涨' })).toHaveTextContent('蘅东光')
    expect(screen.getByRole('region', { name: '北交所下跌' })).toBeEmptyDOMElement()
  })

  it('does not show a false success message when clipboard copying fails', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
    const apiClient = { request: vi.fn().mockResolvedValue(envelope(results)) }
    render(<StockMovesPage apiClient={apiClient} />)

    await screen.findByText('上证')
    fireEvent.click(screen.getByRole('button', { name: '共 2 只股票，全部复制' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('复制失败，请手动复制股票代码。')
    expect(screen.queryByText('已复制 2 只股票代码。')).not.toBeInTheDocument()
  })

  it.each([
    ['preparing', envelope(null, { status: 'error', error: { code: 'DATA_PREPARING' } }), '数据准备中，请稍后刷新。'],
    ['syncing', envelope(null, { status: 'error', error: { code: 'SYNC_IN_PROGRESS' } }), '数据准备中，请稍后刷新。'],
    ['stale', envelope(results, { stale: true, warnings: ['公共日行情版本已更新，正在展示最近可用的分析结果。'] }), '正在展示旧数据'],
  ])('shows the %s data state', async (_name, response, expectedText) => {
    const apiClient = { request: vi.fn().mockResolvedValue(response) }
    render(<StockMovesPage apiClient={apiClient} />)

    expect(await screen.findByText(expectedText)).toBeInTheDocument()
  })

  /*
   * 日期控件在任何数据状态下都必须保持挂载：`useResource` 在 path 变化时
   * 会把 phase 打回 loading，若页面据此整页替换，用户刚在弹层里点完一天，控件就被
   * 卸载重建 —— 弹层、焦点、滚动位置全丢，页面还会先塌成一行提示再弹回来。
   */
  it.each([
    ['loading', () => new Promise(() => {}), null],
    ['error', () => Promise.reject(new Error('network')), '大涨跌幅与大成交量个股数据暂时无法加载。'],
    ['preparing', () => Promise.resolve(envelope(null, { status: 'error', error: { code: 'DATA_PREPARING' } })), '数据准备中，请稍后刷新。'],
    ['syncing', () => Promise.resolve(envelope(null, { status: 'error', error: { code: 'SYNC_IN_PROGRESS' } })), '数据准备中，请稍后刷新。'],
    ['empty', () => Promise.resolve(envelope(null, { status: 'error', error: { code: 'DATA_NOT_AVAILABLE' } })), '暂无数据'],
  ])('keeps the date control mounted while %s', async (_name, request, expectedText) => {
    const apiClient = { request: vi.fn(request) }
    render(<StockMovesPage apiClient={apiClient} />)

    expect(screen.getByLabelText('数据日期')).toBeInTheDocument()
    if (expectedText) {
      expect(await screen.findByText(expectedText)).toBeInTheDocument()
      // 提示只替换内容区，控件仍在页面上。
      expect(screen.getByLabelText('数据日期')).toBeInTheDocument()
    }
    // 没有数据时不渲染依赖数据的复制动作。
    expect(screen.queryByRole('button', { name: /全部复制/ })).not.toBeInTheDocument()
  })

  it('re-requests the same day when「更新于」is clicked', () =>
    expectRefreshRefetches(StockMovesPage, { payload: results, endpoint: '/api/stock-moves/' }))
})
