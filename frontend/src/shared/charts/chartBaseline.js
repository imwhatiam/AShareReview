/*
 * 图表视觉基线：不 import echarts，只产出普通对象。
 *
 * **这里是图表配色的唯一定义处**：图表在 canvas 上渲染，读不到 CSS 变量，所以
 * `src/styles/tokens.css` 里不再放 `--chart-*`。`up` / `down` / `score` 与
 * tokens.css 的 `--color-market-up` / `--color-market-down` / `--color-brand-500`
 * 取值相同，**改任一侧都要手工同步另一侧**（没有构建期校验）。
 *
 * 收在这里的判据是**被两个以上图表消费者共用**：
 *   - 四个业务图共用 `CHART` / `TOOLTIP` / `GRID` / `ANIMATION_DURATION_MS`；
 *   - `categoryAxis` / `valueAxis` 同时被资金流（`features/sector-flow/flowOption.js`）
 *     与百日新高（`chartTheme.js` 的 `trendOption`）使用。
 * 只服务单一图表的件留在各自的构造器里 —— `LEGEND` / `momentumBarAxis` 在
 * `chartTheme.js`，`flowLineSeries` / `clockCategoryAxis` / `END_LABEL_GUTTER` 在
 * `flowOption.js`。不要为了"看起来对称"把单消费者件也搬进来：那只是把共享层
 * 变回杂物间。
 *
 * 本文件会被裸 Node 直接 import（ECharts SSR 脚本），所以所有跨模块 specifier
 * **必须带 `.js` 后缀** —— Node 的 ESM 解析器不做后缀推断。
 */

/*
 * 四个业务图共用的入场动画时长。写成常量而不是散落三处 `320`：切换日期时四张图
 * 的入场节奏必须一致，改一处漏两处就会看出快慢差异。
 */
export const ANIMATION_DURATION_MS = 320

export const CHART = {
  up: '#cf2c2d',
  down: '#0d8f57',
  score: '#3760e6',
  neutral: '#5c6b85',
  grid: '#eceff6',
  axis: '#d8dfea',
  label: '#5c6b85',
}

export const TOOLTIP = {
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

export const GRID = {
  left: 10,
  right: 20,
  top: 56,
  bottom: 6,
  containLabel: true,
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

export function categoryAxis(data) {
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

export function valueAxis(name) {
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
