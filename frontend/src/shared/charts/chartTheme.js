/*
 * 两个盘后模块的业务图 option 构造器：
 *   - `momentumOption` —— 板块动量的竖排分组柱（`sector-momentum/MomentumChart.jsx`）；
 *   - `trendOption`    —— 百日新高的镜像柱（`hundred-day/RatioTrendChart.jsx`）。
 *
 * 资金流那两张图的构造器在 `features/sector-flow/flowOption.js`（它只服务那一个
 * 模块，所以不住在共享层），同样是下列基线的消费者。
 *
 * 配色、提示、网格、入场动画与两根坐标轴全部取自 `chartBaseline.js` —— 那是
 * **四图共用基线的唯一定义处**，本文件不自己写一份颜色或网格。
 *
 * **只导出这两个模块实际消费的 4 个符号**（`momentumOption` / `trendOption` /
 * `scoreAxisMax` / `MOMENTUM_BARS`）；`LEGEND` 与 `momentumBarAxis` 刻意留在模块内
 * —— 它们只在拼一个完整 option 时才有意义，放出去只会让人拼出偏离基线的图。
 */
import {
  ANIMATION_DURATION_MS,
  CHART,
  GRID,
  TOOLTIP,
  categoryAxis,
  valueAxis,
} from './chartBaseline.js'

const LEGEND = {
  type: 'scroll',
  top: 4,
  icon: 'roundRect',
  itemWidth: 10,
  itemHeight: 10,
  itemGap: 14,
  textStyle: { color: CHART.neutral, fontSize: 11 },
}

/*
 * 占比的百分比写法，**入参已经是百分比数值**（`RatioTrendChart` 先把 0.125 换算成
 * 12.5 再传进来），与 `stockFormat.formatRatioPercent`（收 0~1 的比例、自己乘 100）
 * **不是同一个函数**，所以名字必须能区分：这里叫"绝对值百分比"。
 *
 * 取绝对值是因为新低占比为画到横轴下方取了负值，那个负号只是画法。
 */
function formatAbsolutePercent(value) {
  if (value == null) return '—'
  return `${Math.abs(Number(value)).toFixed(2)}%`
}

/*
 * 占比趋势：镜像柱。新高占比画在横轴上方，新低占比取负值画在下方，
 * 一眼看出当天是新高的天下还是新低的天下。刻度与提示都按绝对值显示，
 * 负号只是画法，不代表负占比。
 */
export function trendOption({ dates, newHighRatioSeries, newLowRatioSeries }) {
  return {
    animationDuration: ANIMATION_DURATION_MS,
    tooltip: {
      ...TOOLTIP,
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const rows = Array.isArray(params) ? params : [params]
        const head = rows[0]?.axisValueLabel ?? ''
        const lines = rows.map(
          (row) => `${row.marker}${row.seriesName}：${formatAbsolutePercent(row.value)}`
        )
        return [head, ...lines].join('<br/>')
      },
    },
    legend: { ...LEGEND, data: ['新高占比', '新低占比'] },
    grid: GRID,
    /* 柱要贴着类目居中，不能像折线那样把首尾点压在半格上。 */
    xAxis: { ...categoryAxis(dates), boundaryGap: true },
    yAxis: {
      ...valueAxis('占比（%）'),
      axisLabel: {
        color: CHART.label,
        fontSize: 11,
        formatter: (value) => `${Math.abs(Number(value))}`,
      },
    },
    series: [
      {
        name: '新高占比',
        type: 'bar',
        /* 同一条 stack：两根柱共用同一个 x 位置，一上一下，互不遮挡。 */
        stack: 'ratio',
        barMaxWidth: 18,
        data: newHighRatioSeries,
        itemStyle: { color: CHART.up },
      },
      {
        name: '新低占比',
        type: 'bar',
        stack: 'ratio',
        barMaxWidth: 18,
        data: newLowRatioSeries.map((value) => (value == null ? null : -value)),
        itemStyle: { color: CHART.down },
      },
    ],
  }
}

/*
 * 动量榜柱状图的三个子柱。顺序即图例顺序、即每组的绘制顺序。
 *
 * `value` 把后端字段换算成该子柱自己的数值轴单位（成交占比存的是 0~1 的比例，
 * 轴上按百分比显示），`format` 同时供 tooltip 使用，保证图里和图外写法一致。
 */
export const MOMENTUM_BARS = [
  {
    name: '股票个数（只）',
    color: CHART.score,
    value: (item) => Number(item.stock_count),
    format: (value) => `${Number(value)} 只`,
  },
  {
    name: '平均涨幅（%）',
    color: CHART.up,
    value: (item) => Number(item.average_change_percent),
    format: (value) => `${Number(value).toFixed(2)}%`,
  },
  {
    name: '成交占比（%）',
    color: CHART.neutral,
    /* 后端存的是 0~1 的比例；乘 100 会带出二进制浮点尾巴（0.07 → 7.000000000000001），
       先定到四位小数再交给 ECharts，柱高与 tooltip 才稳定。 */
    value: (item) => Number((Number(item.market_turnover_ratio) * 100).toFixed(4)),
    format: (value) => `${Number(value).toFixed(2)}%`,
  },
]

/*
 * 子柱各自的数值轴。三根子柱量纲不同（只 / 涨幅百分比 / 成交额占比百分比），
 * 共用一根轴会把量级最小的成交占比压成一条平线，所以各占一轴；但都不显示，
 * 图上只留左边那根综合评分轴（见 momentumOption 的 yAxis[0]）。
 */
function momentumBarAxis() {
  return {
    type: 'value',
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { show: false },
    splitLine: { show: false },
  }
}

/*
 * 综合评分轴的上限：按半档向上取整，让 3.56 → 4、17.16 → 20、66.90 → 70。
 * 直接用数据最大值当上限会让刻度出现 17.16 这种读不出来的数字。
 */
export function scoreAxisMax(scores) {
  const max = Math.max(...scores, 0)
  if (!Number.isFinite(max) || max <= 0) return 1
  const step = 10 ** Math.floor(Math.log10(max)) / 2
  return Math.ceil(max / step) * step
}

/*
 * 动量榜：竖排分组柱。类目轴按名次从左到右排列（rank 1 在最左），
 * 每个行业一组三根子柱，对应 MOMENTUM_BARS 的三个指标。
 *
 * 竖轴只保留左边一根综合评分轴：三根子柱各按自己的量纲画（柱高不受影响），
 * 右侧不再有轴，所以这根评分轴是读分数的参考刻度，不对应某一根子柱的高度。
 */
export function momentumOption({ rankings }) {
  const names = rankings.map((item) => item.industry_name)
  return {
    animationDuration: ANIMATION_DURATION_MS,
    tooltip: {
      ...TOOLTIP,
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const rows = Array.isArray(params) ? params : [params]
        const head = rows[0]?.axisValueLabel ?? ''
        const lines = rows.map((row) => {
          const bar = MOMENTUM_BARS[row.seriesIndex]
          const text = bar ? bar.format(row.value) : row.value
          return `${row.marker}${row.seriesName}：${text}`
        })
        return [head, ...lines].join('<br/>')
      },
    },
    legend: { ...LEGEND, data: MOMENTUM_BARS.map((bar) => bar.name) },
    grid: { ...GRID, left: 8, right: 16, top: 44, bottom: 8 },
    xAxis: {
      type: 'category',
      data: names,
      axisLine: { lineStyle: { color: CHART.axis } },
      axisTick: { show: false },
      /* 板块名多为四到八个汉字，半幅图里横排必然互相压住，统一斜排。 */
      axisLabel: {
        color: CHART.label,
        fontSize: 11,
        interval: 0,
        rotate: 45,
        hideOverlap: true,
      },
    },
    yAxis: [
      {
        type: 'value',
        position: 'left',
        min: 0,
        max: scoreAxisMax(rankings.map((item) => Number(item.score))),
        name: '综合评分',
        nameTextStyle: { color: CHART.label, fontSize: 11, align: 'left' },
        nameGap: 14,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: CHART.grid, type: 'dashed' } },
        axisLabel: { color: CHART.label, fontSize: 11 },
      },
      momentumBarAxis(),
      momentumBarAxis(),
      momentumBarAxis(),
    ],
    series: MOMENTUM_BARS.map((bar, index) => ({
      name: bar.name,
      type: 'bar',
      /* 0 号轴留给综合评分，三根子柱各占 1/2/3 号隐藏轴。 */
      yAxisIndex: index + 1,
      barMaxWidth: 12,
      barGap: '25%',
      barCategoryGap: '30%',
      itemStyle: { color: bar.color, borderRadius: [3, 3, 0, 0] },
      data: rankings.map((item) => bar.value(item)),
    })),
  }
}
