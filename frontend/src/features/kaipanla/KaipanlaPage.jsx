import { useEffect, useMemo, useRef, useState } from 'react'

import DataState from '../../shared/DataState'
import FlowControls from '../sector-flow/FlowControls'
import HistoryChart from '../sector-flow/HistoryChart'
import IntradayChart from '../sector-flow/IntradayChart'
import RankingList, { getDefaultSelectedCodes } from '../sector-flow/RankingList'
import useKaipanlaData from './useKaipanlaData'

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

export default function KaipanlaPage({ apiClient }) {
  const [date, setDate] = useState('')
  const [days, setDays] = useState(1)
  const { phase, envelope } = useKaipanlaData({ apiClient, date, days })
  const [selectedCodes, setSelectedCodes] = useState(new Set())
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
    setSelectedCodes(getDefaultSelectedCodes(
      viewData.rankings.inflows,
      viewData.rankings.outflows,
    ))
  }, [envelope?.business_date, viewData])

  function toggleSelectedCode(code) {
    setSelectedCodes((previousCodes) => {
      const nextCodes = new Set(previousCodes)
      if (nextCodes.has(code)) nextCodes.delete(code)
      else nextCodes.add(code)
      return nextCodes
    })
  }

  if (phase === 'loading') {
    return <DataState state="loading" />
  }
  if (phase === 'error') {
    return <DataState state="error" message="开盘啦数据暂时无法加载。" />
  }
  if (envelope?.error?.code === 'DATA_PREPARING') {
    return <DataState state="preparing" />
  }
  if (!viewData || viewData.chart.series.length === 0) {
    return <DataState state="empty" />
  }

  const selectedSeries = viewData.chart.series.filter((item) => selectedCodes.has(item.code))
  const metadata = {
    businessDate: envelope.business_date,
    dataVersion: envelope.data_version,
    stale: envelope.stale,
    partial: envelope.status === 'partial',
    warnings: envelope.warnings,
  }

  return (
    <DataState {...metadata}>
      <section aria-label="开盘啦板块资金流">
        <h2>开盘啦板块资金流</h2>
        <FlowControls
          date={date}
          days={days}
          onDateChange={setDate}
          onWindowChange={setDays}
        />
        {days === 1 ? (
          <IntradayChart {...viewData.chart} series={selectedSeries} />
        ) : (
          <HistoryChart {...viewData.chart} series={selectedSeries} />
        )}
        <div>
          <RankingList
            direction="inflow"
            items={viewData.rankings.inflows}
            selectedCodes={selectedCodes}
            onToggle={toggleSelectedCode}
          />
          <RankingList
            direction="outflow"
            items={viewData.rankings.outflows}
            selectedCodes={selectedCodes}
            onToggle={toggleSelectedCode}
          />
        </div>
      </section>
    </DataState>
  )
}
