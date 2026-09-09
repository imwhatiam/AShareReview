import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

function chartSeries(series) {
  return series.map((item) => ({
    name: item.name,
    type: 'line',
    showSymbol: false,
    connectNulls: false,
    data: item.data,
    lineStyle: {
      color: item.latest_net_inflow >= 0 ? '#c62828' : '#008a4c',
    },
  }))
}

export default function IntradayChart({ timePoints, series }) {
  const containerRef = useRef(null)

  useEffect(() => {
    const chart = echarts.init(containerRef.current)
    const resizeChart = () => chart.resize()
    window.addEventListener('resize', resizeChart)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', boundaryGap: false, data: timePoints },
      yAxis: { type: 'value', name: '累计净额（亿）' },
      series: chartSeries(series),
    })
    return () => {
      window.removeEventListener('resize', resizeChart)
      chart.dispose()
    }
  }, [series, timePoints])

  return <div ref={containerRef} aria-label="分时资金流图" style={{ height: 360 }} />
}
