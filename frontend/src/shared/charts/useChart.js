import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

/*
 * 统一的 ECharts 生命周期：挂载时初始化一次，option 变化时增量更新，
 * 跟随窗口缩放变化，卸载时释放实例。四个业务图共用，避免重复实现。
 */
export default function useChart(option) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current)
    }
    chartRef.current.setOption(option, { notMerge: true })

    const resizeChart = () => chartRef.current?.resize()
    window.addEventListener('resize', resizeChart)

    return () => window.removeEventListener('resize', resizeChart)
  }, [option])

  useEffect(() => () => {
    chartRef.current?.dispose()
    chartRef.current = null
  }, [])

  return containerRef
}
