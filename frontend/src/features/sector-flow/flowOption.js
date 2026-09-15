/*
 * 板块资金流两张图（分时 / 多日）共用的 option 构造器。
 *
 * 归在 feature 目录而不是 `shared/charts/`：`flowOption` 只被本模块的
 * `IntradayChart.jsx` / `HistoryChart.jsx` 消费，它描述的是"资金流长什么样"，
 * 不是全站图表基线。`chartTheme.js` 只留下两个盘后模块的构造器，共享层不再
 * 收集单模块专用件。共用的配色、提示、网格、入场动画与两根坐标轴仍取自
 * `shared/charts/chartBaseline.js` —— 基线只有一份，谁都不许自己拼一套。
 *
 * 本文件会被裸 Node 直接 import（ECharts SSR 脚本，见技能
 * `frontend-visual-verification` 的通道 A），所以所有跨模块 specifier
 * **必须带 `.js` 后缀** —— Node 的 ESM 解析器不做后缀推断。
 */
import { formatFlowAmount } from '../../shared/stockFormat.js'
import {
  ANIMATION_DURATION_MS,
  CHART,
  GRID,
  TOOLTIP,
  categoryAxis,
  valueAxis,
} from '../../shared/charts/chartBaseline.js'

/*
 * 分时轴刻度：只保留"分钟数为 30 的整数倍"的时刻（09:30 / 10:00 / 10:30 / 11:00 /
 * 11:30 / 13:00 / 13:30 / 14:00 / 14:30 / 15:00，整条交易时段共 10 个）。
 * 不能按索引等间隔抽稀 —— 上午 09:30–11:30 共 25 个 5 分钟槽，索引步长会跨过午休
 * 错位一格，下午首个刻度会变成 13:05、末刻度变成 14:55。按真实时刻判断则两个交易
 * 时段都落在整半点上。
 *
 * 密度取半小时而不是十分钟：横轴是整条交易时段，10 分钟一个会让相邻标签在窄屏
 * 直接压在一起（全天 26 个刻度），而半小时一个在任何宽度下都读得清。
 */
function isClockTick(value) {
  const match = /^(\d{2}):(\d{2})$/.exec(String(value))
  if (!match) return true
  return Number(match[2]) % 30 === 0
}

/*
 * 午休边界：11:30 与 13:00 在轴上是**相邻的两个类目**（只隔一个 5 分钟槽 —— 画布越窄槽越窄：
 * 容器 1440px 时 25.6px、1024px 时 17.1px、860px 时 13.8px），而一个 11px 的五位时间标签实测
 * 27.0px 宽 —— 各自居中必然叠成「11:3013:00」。两个时刻都会有数据，谁都不能丢（也不能合并成一条，
 * 那等于少一个刻度），所以把这一对改成**类目项自己的向外对齐**：午休前那条 `align: 'right'`
 * （文本落在自己刻度左侧），下午首条 `align: 'left'`（文本落在自己刻度右侧）。
 *
 * 为什么这样最稳：两者从此分居各自刻度的两侧，**间距恒等于一个槽宽**，与画布宽度无关
 * —— 比"按画布猜"的抽稀/合并可靠。ECharts 6 的类目轴支持给单个 data 项挂 `textStyle`
 * （`AxisBuilder` 会为它单独建一个标签 Model），这是官方途径；`axisLabel.align` 本身
 * 只接受字符串，无法按项区分。轴上不画刻度线（`axisTick.show: false`），标签略微偏离
 * 刻度看不出来。
 *
 * 相邻的整半点只可能出现在午休两侧；只画半天时找不到这一对（`pair` 为 -1），
 * `data` 原样返回纯字符串数组，option 形状与普通类目轴完全一致。
 */
function clockAxisData(timePoints) {
  const pair = timePoints.findIndex(
    (value, index) => index > 0 && isClockTick(value) && isClockTick(timePoints[index - 1]),
  )
  if (pair <= 0) return timePoints
  return timePoints.map((value, index) => {
    if (index === pair - 1) return { value, textStyle: { align: 'right' } }
    if (index === pair) return { value, textStyle: { align: 'left' } }
    return value
  })
}

function clockCategoryAxis(timePoints) {
  return {
    type: 'category',
    boundaryGap: false,
    data: clockAxisData(timePoints),
    axisLine: { lineStyle: { color: CHART.axis } },
    axisTick: { show: false },
    axisLabel: {
      color: CHART.label,
      fontSize: 11,
      /* 刻度由 isClockTick 精确控制，不再交给 ECharts 的防重叠抽稀：
         抽稀按画布宽度猜，窄一点就丢掉半边的刻度，而交易时段的刻度必须始终在场。 */
      hideOverlap: false,
      interval: (index, value) => isClockTick(value),
    },
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
