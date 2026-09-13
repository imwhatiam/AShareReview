import useDateResource from '../../shared/useDateResource'

export const SECTOR_MOMENTUM_ENDPOINT = '/api/sector-momentum/'

/*
 * 这两个错误码都要带正文渲染，而不是打成"加载失败"：
 * - DATA_NOT_AVAILABLE：显式指定的日期确实没有结果（404），永远不会自愈。
 * - SYNC_IN_PROGRESS：该日期的分析正被另一轮生成占用，且连旧结果都没有（409），
 *   是可重试的"稍后会有"，页面按 preparation.state=syncing 显示"数据准备中"。
 */
export const SECTOR_MOMENTUM_ENVELOPE_ERROR_CODES = ['DATA_NOT_AVAILABLE', 'SYNC_IN_PROGRESS']

export default function useSectorMomentum({ apiClient, date }) {
  return useDateResource({
    apiClient,
    date,
    basePath: SECTOR_MOMENTUM_ENDPOINT,
    envelopeErrorCodes: SECTOR_MOMENTUM_ENVELOPE_ERROR_CODES,
  })
}
