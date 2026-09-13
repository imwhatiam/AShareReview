import { useMemo } from 'react'

import useChart from '../../shared/charts/useChart'
import { flowOption } from '../../shared/charts/chartTheme'

export default function HistoryChart({ timePoints, series }) {
  const option = useMemo(
    () => flowOption({
      timePoints,
      series,
      yAxisName: '净流入（亿）',
      showSymbol: true,
    }),
    [series, timePoints],
  )
  const containerRef = useChart(option)

  return (
    <div
      ref={containerRef}
      className="chart"
      aria-label="多日资金流图"
      style={{ height: 380 }}
    />
  )
}
