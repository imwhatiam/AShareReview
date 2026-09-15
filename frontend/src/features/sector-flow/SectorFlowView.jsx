import { useEffect, useMemo, useRef } from 'react'

import DataState from '../../shared/DataState'
import { resolveDataStateName } from '../../shared/dataStateName'
import { resolveDisplayDate } from '../../shared/businessDate'
import useToggleSet from '../../shared/useToggleSet'
import Panel from '../../shared/ui/Panel'
import FlowControls from './FlowControls'
import HistoryChart from './HistoryChart'
import IntradayChart from './IntradayChart'
import RankingList, { getDefaultSelectedCodes } from './RankingList'

function splitDailyRankings(series) {
  return {
    inflows: series.filter((item) => item.latest_net_inflow > 0),
    outflows: series.filter((item) => item.latest_net_inflow < 0),
  }
}

function historyRankings(data) {
  return {
    inflows: (data.period_rankings?.inflows ?? []).map((item) => ({
      ...item,
      latest_net_inflow: item.net_inflow_total,
    })),
    outflows: (data.period_rankings?.outflows ?? []).map((item) => ({
      ...item,
      latest_net_inflow: item.net_inflow_total,
    })),
  }
}

/*
 * 取数失败（网络中断 / 5xx）时的文案。它是这个视图自己的文案，不是调用方参数 ——
 * 原来做成 `errorMessage` prop，4 个调用点传的全是这一句。
 */
const LOAD_FAILED_MESSAGE = '开盘啦数据暂时无法加载。'

function makeHistoryChartData(items, rankedSeries) {
  const chronologicalItems = [...items].reverse()
  return {
    timePoints: chronologicalItems.map((item) => `${item.trade_date} 15:00`),
    series: rankedSeries.map((rankedItem) => ({
      ...rankedItem,
      data: chronologicalItems.map((item) => {
        const dailyItem = (item.series ?? []).find(
          (series) => series.code === rankedItem.code,
        )
        return dailyItem?.data?.at(-1) ?? null
      }),
    })),
  }
}

/*
 * 板块资金流视图：按请求钩子参数化，供资金流类页面复用。
 * 布局为 控件 → 图表 → 流入/流出双榜单；筛选条件在任何数据状态下都保留，
 * 用户切换日期或统计窗口后即使没有数据，也能直接改回去。
 */
export default function SectorFlowView({
  phase,
  envelope,
  date,
  days,
  onDateChange,
  onWindowChange,
  updatedAt = null,
  onRefresh,
}) {
  /*
   * 选中的折线集合与三个排行页的展开集合是同一件事（Set 增删），共用一份实现。
   */
  const {
    values: selectedCodes,
    toggle: toggleSelectedCode,
    replace: replaceSelectedCodes,
  } = useToggleSet()
  /*
   * 已经据以算过默认勾选的那份响应信封。用**信封对象本身**当闸门，而不是业务日期：
   * 它每次取数都是一个新对象，正好等于"每取到一份数据就重算一次"。
   */
  const selectionSourceEnvelope = useRef(null)

  const viewData = useMemo(() => {
    if (!envelope?.data) return null
    if (days === 1) {
      const series = envelope.data.series ?? []
      const rankings = splitDailyRankings(series)
      return {
        chart: { timePoints: envelope.data.time_points ?? [], series },
        rankings,
      }
    }
    const rankings = historyRankings(envelope.data)
    const series = [...rankings.inflows, ...rankings.outflows]
    return {
      chart: makeHistoryChartData(envelope.data.items ?? [], series),
      rankings,
    }
  }, [days, envelope])

  /*
   * 榜单、勾选、折线图是同一份数据的三个视图，必须同进同出 —— 所以**每取到一份新
   * 数据就把默认勾选重算一次**（刷新、换日期、换统计窗口三条路都带回新信封，一条规则
   * 覆盖全部）。
   *
   * 此前这里用 `business_date` 当闸门：同一天内点「更新于 HH:MM」刷新时一律保留旧
   * 勾选。旧勾选的板块一旦掉出新榜单，两个榜单的勾选框会全部空着、折线图也一条线都
   * 不画 —— 用户点刷新看到的是"榜单没刷新好"。换窗口同样会撞上这件事（旧勾选的板块
   * 可能不在新窗口的榜单里），所以闸门不能只看日期。
   *
   * 用信封对象当闸门还顺手挡住了中间态：`days` 已经变了、信封还是上一份时（响应还没
   * 回来），闸门不成立，不会拿旧信封配新窗口算出一份错的默认勾选。
   */
  useEffect(() => {
    if (!envelope || !viewData || selectionSourceEnvelope.current === envelope) {
      return
    }
    selectionSourceEnvelope.current = envelope
    replaceSelectedCodes(getDefaultSelectedCodes(
      viewData.rankings.inflows,
      viewData.rankings.outflows,
    ))
  }, [envelope, viewData, replaceSelectedCodes])

  const stateName = resolveDataStateName(phase, envelope, {
    // 图表一条线都画不出来时（窗口内没有数据）也算空态，但控件仍然保留。
    hasContent: Boolean(viewData) && viewData.chart.series.length > 0,
  })
  /* 日期框始终显示真正生效的业务日期，四个页面共用同一套回填规则。 */
  const displayDate = resolveDisplayDate(date, envelope)
  /*
   * 选中的折线必须 memo 化：图表用 `useMemo(..., [series, timePoints])` 生成
   * ECharts option，内联 `.filter()` 每轮渲染都产出新数组，等于每次勾选、每次父级
   * 重渲染都整图重算 + setOption。selectedCodes 是 state 里的 Set，身份稳定。
   */
  const selectedSeries = useMemo(
    () => (viewData
      ? viewData.chart.series.filter((item) => selectedCodes.has(item.code))
      : []),
    [viewData, selectedCodes],
  )
  const metadata = {
    stale: envelope?.stale,
    warnings: envelope?.warnings,
  }

  return (
    <DataState {...metadata}>
      <Panel>
        <div className="module-stack">
          <FlowControls
            date={displayDate}
            days={days}
            onDateChange={onDateChange}
            onWindowChange={onWindowChange}
            updatedAt={updatedAt}
            onRefresh={onRefresh}
          />

          {stateName ? (
            <DataState
              state={stateName}
              message={stateName === 'error' ? LOAD_FAILED_MESSAGE : undefined}
            />
          ) : (
            <>
              <div className="flow-chart">
                <div className="chart-frame">
                  {days === 1 ? (
                    <IntradayChart {...viewData.chart} series={selectedSeries} />
                  ) : (
                    <HistoryChart {...viewData.chart} series={selectedSeries} />
                  )}
                </div>
              </div>

              <div className="flow-rankings">
                <div className="panel">
                  <div className="panel__body panel__body--tight">
                    <RankingList
                      direction="inflow"
                      items={viewData.rankings.inflows}
                      selectedCodes={selectedCodes}
                      onToggle={toggleSelectedCode}
                    />
                  </div>
                </div>
                <div className="panel">
                  <div className="panel__body panel__body--tight">
                    <RankingList
                      direction="outflow"
                      items={viewData.rankings.outflows}
                      selectedCodes={selectedCodes}
                      onToggle={toggleSelectedCode}
                    />
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </Panel>
    </DataState>
  )
}
