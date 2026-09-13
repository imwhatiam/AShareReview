import { useMemo } from 'react'

import useChart from '../../shared/charts/useChart'
import { trendOption } from '../../shared/charts/chartTheme'

const MAX_TREND_POINTS = 100

function asPercent(value) {
  return value == null ? null : Number(value) * 100
}

export default function RatioTrendChart({ trend }) {
  const visibleTrend = useMemo(() => trend.slice(-MAX_TREND_POINTS), [trend])
  const option = useMemo(() => trendOption({
    dates: visibleTrend.map((point) => point.trade_date),
    newHighRatioSeries: visibleTrend.map((point) => asPercent(point.new_high_ratio)),
    newLowRatioSeries: visibleTrend.map((point) => asPercent(point.new_low_ratio)),
  }), [visibleTrend])
  const containerRef = useChart(option)

  return (
    <div
      ref={containerRef}
      className="chart"
      aria-label="百日新高新低占比趋势图"
      style={{ height: 340 }}
    />
  )
}
