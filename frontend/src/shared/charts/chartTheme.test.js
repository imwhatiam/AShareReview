import { describe, expect, it } from 'vitest'

import { ANIMATION_DURATION_MS } from './chartBaseline'
import {
  MOMENTUM_BARS,
  momentumOption,
  scoreAxisMax,
  trendOption,
} from './chartTheme'

const rankings = [
  {
    rank: 1, industry_name: '板块甲', stock_count: 3,
    average_change_percent: 8.5, market_turnover_ratio: 0.12, score: 3.06,
  },
  {
    rank: 2, industry_name: '板块乙', stock_count: 1,
    average_change_percent: 6.25, market_turnover_ratio: 0.03, score: 0.1875,
  },
]

describe('momentumOption', () => {
  it('draws one vertical bar group per industry, ranked left to right', () => {
    const option = momentumOption({ rankings })

    // 名次最高的行业落在最左边：类目轴按后端顺序，不做反转。
    expect(option.xAxis.type).toBe('category')
    expect(option.xAxis.data).toEqual(['板块甲', '板块乙'])
    // 板块名横排会互相压住，必须斜排。
    expect(option.xAxis.axisLabel.rotate).toBeGreaterThan(0)

    // 每个行业一组三根子柱。
    expect(option.series).toHaveLength(3)
    expect(option.series.map((series) => series.name)).toEqual(
      MOMENTUM_BARS.map((bar) => bar.name),
    )
    expect(option.series.every((series) => series.type === 'bar')).toBe(true)
  })

  it('keeps exactly one visible 综合评分 axis and gives every bar its own hidden scale', () => {
    const option = momentumOption({ rankings })

    const visible = option.yAxis.filter((axis) => axis.axisLabel.show !== false)
    expect(visible).toHaveLength(1)
    expect(visible[0]).toMatchObject({ position: 'left', name: '综合评分', min: 0 })
    expect(visible[0].max).toBe(scoreAxisMax(rankings.map((item) => item.score)))

    /*
     * 三根子柱量纲不同（只数 / 百分数 / 百分数），各占一根隐藏轴，各按各的刻度画。
     * 断的是"每根柱都有自己的轴、且都不是那根可见轴"，而不是轴的条数或下标的字面
     * 值 —— 后者是实现细节，调整轴的排列顺序就会让用例碎掉，却什么行为都没变。
     */
    const visibleIndex = option.yAxis.indexOf(visible[0])
    const indexes = option.series.map((series) => series.yAxisIndex)
    expect(new Set(indexes).size).toBe(option.series.length)
    for (const index of indexes) {
      expect(index).not.toBe(visibleIndex)
      expect(option.yAxis[index]).toBeDefined()
      expect(option.yAxis[index].axisLabel.show).toBe(false)
      expect(option.yAxis[index].splitLine.show).toBe(false)
    }
  })

  it('feeds each bar its own metric, with the turnover ratio turned into a percentage', () => {
    const option = momentumOption({ rankings })

    // 期望值从 fixture 推出来，而不是抄一份字面量：fixture 改了数值，这里自动跟上，
    // 用例仍然只盯"哪根柱喂的是哪个字段"。
    expect(option.series[0].data).toEqual(rankings.map((item) => item.stock_count))
    expect(option.series[1].data).toEqual(rankings.map((item) => item.average_change_percent))
    // 后端存的是 0~1 的比例，轴上按百分比显示（0.12 → 12），且不留浮点尾巴
    // （0.03 * 100 在浮点里是 3.0000000000000004）。
    expect(option.series[2].data).toEqual(
      rankings.map((item) => Number((item.market_turnover_ratio * 100).toFixed(2))),
    )
  })

  it('names the units in the legend and spells the same values out in the tooltip', () => {
    const option = momentumOption({ rankings })

    expect(option.legend.data).toEqual(['股票个数（只）', '平均涨幅（%）', '成交占比（%）'])

    const marker = '<i></i>'
    const params = [
      { seriesIndex: 0, seriesName: '股票个数（只）', value: 3, marker, axisValueLabel: '板块甲' },
      { seriesIndex: 1, seriesName: '平均涨幅（%）', value: 8.5, marker, axisValueLabel: '板块甲' },
      { seriesIndex: 2, seriesName: '成交占比（%）', value: 12, marker, axisValueLabel: '板块甲' },
    ]

    expect(option.tooltip.formatter(params)).toBe([
      '板块甲',
      `${marker}股票个数（只）：3 只`,
      `${marker}平均涨幅（%）：8.50%`,
      `${marker}成交占比（%）：12.00%`,
    ].join('<br/>'))
  })
})

describe('scoreAxisMax', () => {
  it('rounds the 综合评分 ceiling up to a readable tick', () => {
    expect(scoreAxisMax([3.56, 17.16])).toBe(20)
    expect(scoreAxisMax([13.03, 66.9])).toBe(70)
    expect(scoreAxisMax([3.56])).toBe(4)
  })

  it('never returns a zero-height axis', () => {
    expect(scoreAxisMax([])).toBe(1)
    expect(scoreAxisMax([0, 0])).toBe(1)
  })
})

describe('trendOption', () => {
  const dates = ['2026-09-08', '2026-09-09']

  it('draws 新高 above and 新低 below the zero line as mirror bars', () => {
    const option = trendOption({
      dates,
      newHighRatioSeries: [12.5, 20],
      newLowRatioSeries: [25, 10],
    })

    expect(option.series.map((series) => series.type)).toEqual(['bar', 'bar'])
    expect(option.series.map((series) => series.name)).toEqual(['新高占比', '新低占比'])
    expect(option.series[0].data).toEqual([12.5, 20])
    // 新低取负值才会画到横轴下方；同一条 stack 让两根柱共用同一个 x 位置。
    expect(option.series[1].data).toEqual([-25, -10])
    expect(option.series[0].stack).toBe(option.series[1].stack)
    // 柱要贴着类目居中，不能像折线那样把首尾点压在半格上。
    expect(option.xAxis.boundaryGap).toBe(true)
  })

  it('shows the ratios as absolute percentages on the axis and in the tooltip', () => {
    const option = trendOption({ dates, newHighRatioSeries: [20], newLowRatioSeries: [10] })

    expect(option.yAxis.axisLabel.formatter(-25)).toBe('25')

    const marker = '<i></i>'
    const params = [
      { seriesIndex: 0, seriesName: '新高占比', value: 20, marker, axisValueLabel: '2026-09-09' },
      { seriesIndex: 1, seriesName: '新低占比', value: -10, marker, axisValueLabel: '2026-09-09' },
    ]

    expect(option.tooltip.formatter(params)).toBe([
      '2026-09-09',
      `${marker}新高占比：20.00%`,
      `${marker}新低占比：10.00%`,
    ].join('<br/>'))
  })

  it('keeps days without a valid ratio empty instead of drawing a zero bar', () => {
    const option = trendOption({
      dates,
      newHighRatioSeries: [null, 20],
      newLowRatioSeries: [null, null],
    })

    expect(option.series[0].data).toEqual([null, 20])
    expect(option.series[1].data).toEqual([null, null])
  })
})

/*
 * 四张业务图共用同一个入场动画时长（资金流那两张由
 * `features/sector-flow/flowOption.test.js` 钉住）。断的是"都取自
 * `chartBaseline.ANIMATION_DURATION_MS`"而不是 320 这个字面值 —— 时长本身可以调，
 * 但调的时候必须几张图一起调，漂移才是 bug。
 */
describe('chart entrance animation', () => {
  it('takes the entrance animation from the shared baseline', () => {
    const options = [
      momentumOption({ rankings }),
      trendOption({ dates: ['2026-09-08'], newHighRatioSeries: [12.5], newLowRatioSeries: [0] }),
    ]

    expect(options.map((option) => option.animationDuration)).toEqual([
      ANIMATION_DURATION_MS,
      ANIMATION_DURATION_MS,
    ])
  })
})
