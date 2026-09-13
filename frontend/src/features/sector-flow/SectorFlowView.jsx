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
 * 板块资金流视图：按请求钩子和错误提示参数化，供资金流类页面复用。
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
  errorMessage,
  refreshedAt = null,
}) {
  /*
   * 选中的折线集合与三个排行页的展开集合是同一件事（Set 增删），共用一份实现。
   */
  const {
    values: selectedCodes,
    toggle: toggleSelectedCode,
    replace: replaceSelectedCodes,
  } = useToggleSet()
  const selectedBusinessDate = useRef(null)

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

  useEffect(() => {
    const businessDate = envelope?.business_date
    if (!businessDate || !viewData || selectedBusinessDate.current === businessDate) {
      return
    }
    selectedBusinessDate.current = businessDate
    replaceSelectedCodes(getDefaultSelectedCodes(
      viewData.rankings.inflows,
      viewData.rankings.outflows,
    ))
  }, [envelope?.business_date, viewData, replaceSelectedCodes])

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
            refreshedAt={refreshedAt}
          />

          {stateName ? (
            <DataState
              state={stateName}
              message={stateName === 'error' ? errorMessage : undefined}
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
