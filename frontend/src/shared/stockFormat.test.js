import { describe, expect, it } from 'vitest'

import {
  formatChangePercent,
  formatDecimal,
  formatFlowAmount,
  formatRatioPercent,
  formatTurnover,
  formatTurnoverInYi,
  stockLabel,
} from './stockFormat'

/*
 * 这组断言是"三页共用一份数字写法"的契约。要断的是**缺失值不能伪装成 0** ——
 * 曾经 `formatChangePercent('')` 返回 `0.00%`，把"没有当日行情"显示成了平盘。
 */
describe('stockFormat', () => {
  it.each([null, undefined, '', 'abc', NaN])('renders %s as a dash', (value) => {
    expect(formatChangePercent(value)).toBe('—')
    expect(formatTurnover(value)).toBe('—')
    expect(formatTurnoverInYi(value)).toBe('—')
    expect(formatRatioPercent(value)).toBe('—')
    expect(formatDecimal(value)).toBe('—')
  })

  it('keeps an explicit zero as a real number, not a dash', () => {
    expect(formatChangePercent(0)).toBe('0.00%')
    expect(formatChangePercent('0')).toBe('0.00%')
    expect(formatTurnover(0)).toBe('0.00亿')
  })

  it('signs only the positive changes', () => {
    expect(formatChangePercent(3.456)).toBe('+3.46%')
    expect(formatChangePercent(-3.456)).toBe('-3.46%')
  })

  it('converts ratios to percent and yuan to 亿', () => {
    expect(formatRatioPercent(0.0523)).toBe('5.23%')
    expect(formatRatioPercent('0.0523')).toBe('5.23%')
    expect(formatTurnover(123456789)).toBe('1.23亿')
    expect(formatTurnoverInYi(123456789)).toBe('1.23')
  })

  it('honours the requested precision', () => {
    expect(formatDecimal(1.23456, 4)).toBe('1.2346')
    expect(formatDecimal(1.23456)).toBe('1.23')
  })

  it('writes a stock line with both metrics', () => {
    expect(stockLabel({ name: '贵州茅台', change_percent: 1.2, turnover: 123456789 }))
      .toBe('贵州茅台（+1.20%，1.23亿）')
    expect(stockLabel({ name: '停牌股', change_percent: null, turnover: null }))
      .toBe('停牌股（—，—）')
  })

  /*
   * 资金净额这一份写法同时供折线右端标签与资金流榜单使用，所以断言用的是
   * `flowView.test.jsx` 那组字面量（`流入行业1 +3.4亿` / `流出行业2 -2.1亿`）：
   * 任一侧自己另写一份实现，两处必有一处变红。
   *
   * 缺失值返回 `null` 而不是破折号 —— 图表要据此决定"只画板块名"，破折号会污染标签。
   */
  it('writes net inflow amounts the same way the chart and the ranking list do', () => {
    expect(formatFlowAmount(3.4)).toBe('+3.4亿')
    expect(formatFlowAmount(-2.1)).toBe('-2.1亿')
    expect(formatFlowAmount(0)).toBe('0.0亿')
    expect(formatFlowAmount('3.4')).toBe('+3.4亿')
    for (const missing of [null, undefined, '', 'abc', NaN]) {
      expect(formatFlowAmount(missing)).toBeNull()
    }
  })
})
