import { useState } from 'react'

import SectorFlowView from '../sector-flow/SectorFlowView'
import useKaipanlaData from './useKaipanlaData'

export default function KaipanlaPage({ apiClient }) {
  const [date, setDate] = useState('')
  const [days, setDays] = useState(1)
  const { phase, envelope, refreshedAt } = useKaipanlaData({ apiClient, date, days })

  /*
   * 所有统计窗口都以最近一个已发布交易日为终点：点任一窗口按钮都清空手选日期，
   * 由后端按最新交易日往回取 1/5/10/20 个交易日，避免停留在之前选中的历史日期上。
   * 用户若显式选择日期，则该日期成为窗口终点。
   */
  function handleWindowChange(nextDays) {
    setDays(nextDays)
    setDate('')
  }

  return (
    <SectorFlowView
      phase={phase}
      envelope={envelope}
      date={date}
      days={days}
      onDateChange={setDate}
      onWindowChange={handleWindowChange}
      errorMessage="开盘啦数据暂时无法加载。"
      refreshedAt={refreshedAt}
    />
  )
}
