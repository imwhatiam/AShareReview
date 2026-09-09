import { useEffect, useState } from 'react'

const RANKING_LIMIT = 25

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
  const [result, setResult] = useState({ phase: 'loading', envelope: null })

  useEffect(() => {
    const controller = new AbortController()
    setResult({ phase: 'loading', envelope: null })

    apiClient.request(buildKaipanlaPath({ date, days }), { signal: controller.signal })
      .then((envelope) => {
        if (!controller.signal.aborted) {
          setResult({ phase: 'ready', envelope })
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setResult({ phase: 'error', envelope: null })
        }
      })

    return () => controller.abort()
  }, [apiClient, date, days])

  return result
}
