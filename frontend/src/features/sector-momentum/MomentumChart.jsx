import { useMemo } from 'react'

import useChart from '../../shared/charts/useChart'
import { momentumOption } from '../../shared/charts/chartTheme'

/*
 * 名次即从左到右的顺序：后端已按评分从高到低排好，这里不再反转，
 * 评分最高的行业落在最左边的柱组上。
 */
export default function MomentumChart({ rankings }) {
  const option = useMemo(() => momentumOption({ rankings }), [rankings])
  const containerRef = useChart(option)

  return (
    <div
      ref={containerRef}
      className="chart"
      aria-label="行业动量评分图"
      /* 板块名在类目轴上斜排 45°，比横排柱状图需要更多底部空间。 */
      style={{ height: 360 }}
    />
  )
}
