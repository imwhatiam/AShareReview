import useDateResource from '../../shared/useDateResource'

export const HUNDRED_DAY_ENDPOINT = '/api/hundred-day/'

/*
 * 这三个错误码都要带正文渲染，而不是打成"加载失败"：
 * - DATA_NOT_AVAILABLE：该日期没有结果（404）
 * - INSUFFICIENT_HISTORY：该日期之前的行情不足 199 个交易日（404），
 *   缺的是更早的历史，永远不会自愈，用户需要看到原因而不是空白页。
 * - SYNC_IN_PROGRESS：该日期的分析正被另一轮生成占用且连旧结果都没有（409），
 *   是可重试的"稍后会有"，页面按 preparation.state=syncing 显示"数据准备中"。
 */
export const HUNDRED_DAY_ENVELOPE_ERROR_CODES = [
  'DATA_NOT_AVAILABLE', 'INSUFFICIENT_HISTORY', 'SYNC_IN_PROGRESS',
]

export default function useHundredDay({ apiClient, date }) {
  return useDateResource({
    apiClient,
    date,
    basePath: HUNDRED_DAY_ENDPOINT,
    envelopeErrorCodes: HUNDRED_DAY_ENVELOPE_ERROR_CODES,
  })
}
