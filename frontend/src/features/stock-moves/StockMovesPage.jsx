import { useState } from 'react'

import { resolveDataStateName } from '../../shared/dataStateName'
import { resolveDisplayDate } from '../../shared/businessDate'
import DatePicker from '../../shared/ui/DatePicker'
import Icon from '../../shared/ui/Icon'
import ModulePage from '../../shared/ui/ModulePage'
import RefreshStamp from '../../shared/RefreshStamp'
import StockMoveBoard from './StockMoveBoard'
import useStockMoves from './useStockMoves'

const ERROR_MESSAGE = '大涨跌幅与大成交量个股数据暂时无法加载。'

export default function StockMovesPage({ apiClient }) {
  const [date, setDate] = useState('')
  const [copyResult, setCopyResult] = useState(null)
  const { phase, envelope, updatedAt, refresh } = useStockMoves({ apiClient, date })

  const data = envelope?.data ?? null
  const stateName = resolveDataStateName(phase, envelope, { hasContent: Boolean(data) })
  const displayDate = resolveDisplayDate(date, envelope)

  async function copyStockCodes() {
    try {
      // 后端返回的 stock_codes 已按页面分组顺序排好，这里只负责逗号分隔，
      // 让粘贴到行情软件里的代码顺序和页面上的表格一致。
      await navigator.clipboard.writeText((data?.stock_codes ?? []).join(','))
      setCopyResult({ kind: 'success', message: `已复制 ${data.distinct_stock_count} 只股票代码。` })
    } catch {
      setCopyResult({ kind: 'error', message: '复制失败，请手动复制股票代码。' })
    }
  }

  return (
    <ModulePage
      envelope={envelope}
      stateName={stateName}
      message={stateName === 'error' ? ERROR_MESSAGE : undefined}
      toolbar={(
        <>
          <DatePicker id="stock-moves-date" value={displayDate} onChange={setDate} />
          <RefreshStamp updatedAt={updatedAt} onRefresh={refresh} />
          {/* "复制"依赖数据，没数据时不渲染。 */}
          {data && (
            <div className="toolbar__actions">
              {/*
               * 复制是一个纯文字动作，不带边框和底色（.btn--ghost），
               * 图标跟在"复制"后面，让整行读起来就是一句文案。
               */}
              <button type="button" className="btn btn--ghost" onClick={copyStockCodes}>
                共 {data.distinct_stock_count} 只股票，全部复制
                <Icon name="copy" size={15} />
              </button>
            </div>
          )}
        </>
      )}
      notice={copyResult && (
        <p
          role={copyResult.kind === 'success' ? 'status' : 'alert'}
          className={`feedback feedback--${copyResult.kind}`}
        >
          {copyResult.message}
        </p>
      )}
    >
      <StockMoveBoard groups={data?.groups ?? {}} />
    </ModulePage>
  )
}
