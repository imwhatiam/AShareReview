import { useState } from 'react'

import DataState from '../../shared/DataState'
import StockGroupTable from './StockGroupTable'
import useStockMoves from './useStockMoves'

const GROUPS = [
  ['sse_rise', '上证上涨'],
  ['sse_fall', '上证下跌'],
  ['szse_rise', '深证上涨'],
  ['szse_fall', '深证下跌'],
]

export default function StockMovesPage({ apiClient }) {
  const [date, setDate] = useState('')
  const [copyResult, setCopyResult] = useState(null)
  const { phase, envelope } = useStockMoves({ apiClient, date })

  async function copyStockCodes() {
    try {
      await navigator.clipboard.writeText((envelope?.data?.stock_codes ?? []).join('\n'))
      setCopyResult({ kind: 'success', message: `已复制 ${envelope.data.distinct_stock_count} 只股票代码。` })
    } catch {
      setCopyResult({ kind: 'error', message: '复制失败，请手动复制股票代码。' })
    }
  }

  if (phase === 'loading') return <DataState state="loading" />
  if (phase === 'error') {
    return <DataState state="error" message="大涨跌幅与大成交量个股数据暂时无法加载。" />
  }
  if (envelope?.error?.code === 'DATA_PREPARING') return <DataState state="preparing" />
  if (envelope?.error?.code === 'DATA_NOT_AVAILABLE') return <DataState state="empty" />
  if (!envelope?.data) return <DataState state="empty" />

  const metadata = {
    businessDate: envelope.business_date,
    dataVersion: envelope.data_version,
    stale: envelope.stale,
    partial: envelope.status === 'partial',
    warnings: envelope.warnings,
  }
  const groups = envelope.data.groups ?? {}

  return (
    <DataState {...metadata}>
      <section aria-label="大涨跌幅与大成交量个股">
        <h2>大涨跌幅与大成交量个股</h2>
        <label htmlFor="stock-moves-date">数据日期</label>
        <input
          id="stock-moves-date"
          type="date"
          value={date}
          onChange={(event) => setDate(event.target.value)}
        />
        <p>全部去重股票：{envelope.data.distinct_stock_count} 只</p>
        <button type="button" onClick={copyStockCodes}>复制全部</button>
        {copyResult && (
          <p role={copyResult.kind === 'success' ? 'status' : 'alert'}>{copyResult.message}</p>
        )}
        <div>
          {GROUPS.map(([key, title]) => (
            <StockGroupTable key={key} title={title} items={groups[key] ?? []} />
          ))}
        </div>
      </section>
    </DataState>
  )
}
