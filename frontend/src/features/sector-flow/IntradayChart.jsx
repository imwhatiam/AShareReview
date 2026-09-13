import { useMemo } from 'react'

import useChart from '../../shared/charts/useChart'
import { flowOption } from '../../shared/charts/chartTheme'

export default function IntradayChart({ timePoints, series }) {
  const option = useMemo(
    () => flowOption({
      timePoints,
      series,
      yAxisName: '累计净额（亿）',
      showSymbol: false,
      timeAxis: true,
    }),
    [series, timePoints],
  )
  const containerRef = useChart(option)

  return (
    <div
      ref={containerRef}
      className="chart"
      aria-label="分时资金流图"
      style={{ height: 380 }}
    />
  )
}
