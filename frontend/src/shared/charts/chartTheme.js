/*
 * 图表视觉基线：不 import echarts，只产出普通对象。
 * 四个业务图共用同一套网格、坐标、提示与配色，保证观感一致。
 *
 * **这是图表配色的唯一定义处**：图表在 canvas 上渲染，读不到 CSS 变量，所以
 * `src/styles/tokens.css` 里不再放 `--chart-*`。`up` / `down` / `score` 与
 * tokens.css 的 `--color-market-up` / `--color-market-down` / `--color-brand-500`
 * 取值相同，**改任一侧都要手工同步另一侧**（没有构建期校验）。
 *
 * 数字写法不在这里自己写一份：金额/百分比全部取自 `shared/stockFormat`。本文件
 * 会被裸 Node 直接 import，所以那个 specifier **必须带 `.js` 后缀**
 * —— Node 的 ESM 解析器不做后缀推断。
 *
 * **只导出四个业务图实际消费的 5 个符号**（`momentumOption` / `trendOption` /
 * `flowOption` / `scoreAxisMax` / `MOMENTUM_BARS`）；`CHART`、`TOOLTIP`、`GRID`、
 * `LEGEND` 与各 axis / series 工厂刻意留在模块内 —— 它们只在拼一个完整 option 时
 * 才有意义，放出去只会让人拼出偏离基线的图。
 */
import { formatFlowAmount } from '../stockFormat.js'

/*
 * 四个业务图共用的入场动画时长。写成常量而不是散落三处 `320`：切换日期时四张图
 * 的入场节奏必须一致，改一处漏两处就会看出快慢差异。
 */
const ANIMATION_DURATION_MS = 320

const CHART = {
  up: '#cf2c2d',
  down: '#0d8f57',
  score: '#3760e6',
  neutral: '#5c6b85',
  grid: '#eceff6',
  axis: '#d8dfea',
  label: '#5c6b85',
}

const TOOLTIP = {
  trigger: 'axis',
  backgroundColor: '#ffffff',
  borderColor: '#e2e7f0',
  borderWidth: 1,
  padding: [10, 12],
  textStyle: { color: '#1a2438', fontSize: 12 },
  extraCssText: 'box-shadow: 0 8px 24px rgba(16, 24, 40, 0.12); border-radius: 10px;',
  axisPointer: {
    type: 'line',
    lineStyle: { color: '#cdd6e5', type: 'dashed', width: 1 },
  },
}

const GRID = {
  left: 10,
  right: 20,
  top: 56,
  bottom: 6,
  containLabel: true,
}

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
 * 类目轴刻度压缩：'2026-09-10 15:00' → '09-10'。
 * 只影响坐标轴上的显示文本，option.xAxis.data 始终保留原始值。
 */
function shortCategoryLabel(value) {
  const text = String(value)
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(text)
  return match ? `${match[2]}-${match[3]}` : text
}

function categoryAxis(data) {
  return {
    type: 'category',
    boundaryGap: false,
    data,
    axisLine: { lineStyle: { color: CHART.axis } },
    axisTick: { show: false },
    axisLabel: {
      color: CHART.label,
      fontSize: 11,
      hideOverlap: true,
      formatter: shortCategoryLabel,
    },
  }
}

/*
 * 分时轴刻度：只保留"分钟数为 10 的整数倍"的时刻（09:30 / 09:40 / … / 11:30 /
 * 13:00 / … / 15:00）。不能按索引等间隔抽稀 —— 上午 09:30–11:30 共 25 个 5 分钟槽，
 * 索引步长会跨过午休错位一格，导致下午首个刻度变成 13:05、末刻度变成 14:55。
 * 按真实时刻判断则两个交易时段都对齐到整十分钟。
 */
function isClockTick(value) {
  const match = /^(\d{2}):(\d{2})$/.exec(String(value))
  if (!match) return true
  return Number(match[2]) % 10 === 0
}

function clockCategoryAxis(data) {
  return {
    type: 'category',
    boundaryGap: false,
    data,
    axisLine: { lineStyle: { color: CHART.axis } },
    axisTick: { show: false },
    axisLabel: {
      color: CHART.label,
      fontSize: 11,
      /* 刻度由 isClockTick 精确控制，不再交给 ECharts 的防重叠抽稀，
         否则午休两侧相邻的 11:30 与 13:00 可能被误判为重叠而丢掉 13:00。 */
      hideOverlap: false,
      interval: (index, value) => isClockTick(value),
    },
  }
}

function valueAxis(name) {
  return {
    type: 'value',
    name,
    nameTextStyle: { color: CHART.label, fontSize: 11, align: 'left' },
    nameGap: 18,
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: CHART.grid, type: 'dashed' } },
    axisLabel: { color: CHART.label, fontSize: 11 },
  }
}

/* 按资金方向着色的折线：红为净流入，绿为净流出。 */
function flowLineSeries(series, { showSymbol = true } = {}) {
  return series.map((item) => {
    const value = Number(item.latest_net_inflow)
    const color = value >= 0 ? CHART.up : CHART.down
    return {
      name: item.name,
      type: 'line',
      smooth: 0.2,
      showSymbol,
      symbol: 'circle',
      symbolSize: showSymbol ? 5 : 4,
      connectNulls: false,
      emphasis: { focus: 'series', scale: 1.4 },
      lineStyle: { color, width: 2 },
      itemStyle: { color },
      data: item.data,
      /* 取消顶部图例后，板块名与资金净额常驻在每条折线的右端。 */
      endLabel: {
        show: true,
        distance: 6,
        fontSize: 11,
        fontWeight: 600,
        color,
        formatter: ({ value: lastValue, seriesName }) => {
          const amount = formatFlowAmount(lastValue)
          return amount ? `${seriesName} ${amount}` : seriesName
        },
      },
      /* 多条折线在右端收敛时把标签上下错开，避免互相压住。 */
      labelLayout: { moveOverlap: 'shiftY' },
    }
  })
}

/*
 * 线端常驻标签需要预留的横向空间，单位 px。
 * 标签画在 grid 右边界之外，可用宽度 = END_LABEL_GUTTER - endLabel.distance(6)，
 * 不够就会被画布裁掉，等于丢掉板块名。按布局库里的真实板块名实测（600 11px 无衬线）：
 * 「宁夏回族自治区 +12.3亿」118.9px，把金额换成三位数亿级约 125px；
 * 目前最长板块名为 7 个汉字（广西壮族自治区 / 宁夏回族自治区），
 * 取 152 可覆盖「7~8 个汉字 + 三位数亿级」的最坏组合。
 */
const END_LABEL_GUTTER = 152

export function flowOption({ timePoints, series, yAxisName, showSymbol, timeAxis = false }) {
  return {
    color: [CHART.up, CHART.down],
    animationDuration: ANIMATION_DURATION_MS,
    tooltip: { ...TOOLTIP, axisPointer: { ...TOOLTIP.axisPointer } },
    /* 板块标识改为折线右端的 endLabel，顶部不再渲染图例。
       top 只需给 y 轴名称（nameGap 18 + 字号 11）留出空间。 */
    grid: { ...GRID, top: 36, right: END_LABEL_GUTTER },
    xAxis: timeAxis ? clockCategoryAxis(timePoints) : categoryAxis(timePoints),
    yAxis: valueAxis(yAxisName),
    series: flowLineSeries(series, { showSymbol }),
  }
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
