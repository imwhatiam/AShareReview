import useDateResource from '../../shared/useDateResource'

const STOCK_MOVES_ENDPOINT = '/api/stock-moves/'

/*
 * 这两个错误码都要带正文渲染，而不是打成"加载失败"：
 * - DATA_NOT_AVAILABLE：显式指定的日期确实没有结果（404），永远不会自愈。
 * - SYNC_IN_PROGRESS：该日期的分析正被另一轮生成占用，且连旧结果都没有（409），
 *   是可重试的"稍后会有"，页面按 preparation.state=syncing 显示"数据准备中"。
 */
const STOCK_MOVES_ENVELOPE_ERROR_CODES = ['DATA_NOT_AVAILABLE', 'SYNC_IN_PROGRESS']

export default function useStockMoves({ apiClient, date }) {
  return useDateResource({
    apiClient,
    date,
    basePath: STOCK_MOVES_ENDPOINT,
    envelopeErrorCodes: STOCK_MOVES_ENVELOPE_ERROR_CODES,
  })
}
