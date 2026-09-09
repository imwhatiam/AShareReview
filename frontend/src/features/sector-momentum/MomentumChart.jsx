import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

export default function MomentumChart({ rankings }) {
  const containerRef = useRef(null)

  useEffect(() => {
    const chart = echarts.init(containerRef.current)
    const resizeChart = () => chart.resize()
    window.addEventListener('resize', resizeChart)
    chart.setOption({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'value', name: '综合评分' },
      yAxis: { type: 'category', data: rankings.map((item) => item.industry_name).reverse() },
      series: [{
        type: 'bar', data: rankings.map((item) => item.score).reverse(),
        itemStyle: { color: '#c62828' },
      }],
    })
    return () => {
      window.removeEventListener('resize', resizeChart)
      chart.dispose()
    }
  }, [rankings])

  return <div ref={containerRef} aria-label="行业动量评分图" style={{ height: 320 }} />
}
