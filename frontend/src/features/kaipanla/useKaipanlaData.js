import usePolledResource from '../../shared/usePolledResource'

const RANKING_LIMIT = 25

/*
 * 板块资金流盘中每 5 分钟自动重取，与 fetch_kaipanla_sector_fund_flow 的采集
 * 节奏一致。只有默认入口（未手选日期、单日视图）才轮询：翻看历史或看多日趋势
 * 时数据不会变，没必要反复请求。
 */
export const KAIPANLA_POLL_INTERVAL_MS = 5 * 60 * 1000

/*
 * 板块资金流页面自己把 404（DATA_NOT_AVAILABLE）当错误处理，保持既有行为；
 * 但 409 SYNC_IN_PROGRESS 表示"该快照正被另一轮采集占用且连旧快照都没有"，
 * 是可重试的"稍后会有"，必须带正文渲染成"数据准备中"而不是加载失败。
 */
export const KAIPANLA_ENVELOPE_ERROR_CODES = ['SYNC_IN_PROGRESS']

function buildQuery({ date, days }) {
  const query = new URLSearchParams()
  if (date) query.set('date', date)
  if (days > 1) query.set('days', String(days))
  query.set('inflow_top', String(RANKING_LIMIT))
  query.set('outflow_top', String(RANKING_LIMIT))
  return query.toString()
}

export function buildKaipanlaPath({ date, days }) {
  const endpoint = days === 1
    ? '/api/kaipanla/sectors/intraday/'
    : '/api/kaipanla/sectors/intraday/history/'
  return `${endpoint}?${buildQuery({ date, days })}`
}

export default function useKaipanlaData({ apiClient, date, days }) {
  const pollIntervalMs = !date && days === 1 ? KAIPANLA_POLL_INTERVAL_MS : 0
  return usePolledResource({
    apiClient,
    path: buildKaipanlaPath({ date, days }),
    pollIntervalMs,
    envelopeErrorCodes: KAIPANLA_ENVELOPE_ERROR_CODES,
  })
}
