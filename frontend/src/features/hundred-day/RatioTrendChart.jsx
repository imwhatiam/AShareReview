import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

const MAX_TREND_POINTS = 100

function asPercent(value) {
  return value == null ? null : Number(value) * 100
}

export default function RatioTrendChart({ trend }) {
  const containerRef = useRef(null)
  const visibleTrend = trend.slice(-MAX_TREND_POINTS)

  useEffect(() => {
    const chart = echarts.init(containerRef.current)
    const resizeChart = () => chart.resize()
    window.addEventListener('resize', resizeChart)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['新高占比', '新低占比'] },
      xAxis: { type: 'category', data: visibleTrend.map((point) => point.trade_date) },
      yAxis: { type: 'value', name: '占比（%）' },
      series: [
        {
          name: '新高占比', type: 'line', connectNulls: false,
          data: visibleTrend.map((point) => asPercent(point.new_high_ratio)),
          itemStyle: { color: '#c62828' },
        },
        {
          name: '新低占比', type: 'line', connectNulls: false,
          data: visibleTrend.map((point) => asPercent(point.new_low_ratio)),
          itemStyle: { color: '#008a4c' },
        },
      ],
    })
    return () => {
      window.removeEventListener('resize', resizeChart)
      chart.dispose()
    }
  }, [visibleTrend])

  return <div ref={containerRef} aria-label="百日新高新低占比趋势图" style={{ height: 320 }} />
}
