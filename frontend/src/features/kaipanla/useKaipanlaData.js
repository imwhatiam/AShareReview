import useResource from '../../shared/useResource'

const RANKING_LIMIT = 25

/*
 * 板块资金流页面自己把 404（DATA_NOT_AVAILABLE）当错误处理，保持既有行为；
 * 但 409 SYNC_IN_PROGRESS 表示"该快照正被另一轮采集占用且连旧快照都没有"，
 * 是可重试的"稍后会有"，必须带正文渲染成"数据准备中"而不是加载失败。
 */
const KAIPANLA_ENVELOPE_ERROR_CODES = ['SYNC_IN_PROGRESS']

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
  return useResource({
    apiClient,
    path: buildKaipanlaPath({ date, days }),
    envelopeErrorCodes: KAIPANLA_ENVELOPE_ERROR_CODES,
  })
}
