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

export function buildEastmoneyPath({ date, days }) {
  const endpoint = days === 1
    ? '/api/eastmoney/sectors/intraday/'
    : '/api/eastmoney/sectors/intraday/history/'
  return `${endpoint}?${buildQuery({ date, days })}`
}

export default function useEastmoneyData({ apiClient, date, days }) {
  const [result, setResult] = useState({ phase: 'loading', envelope: null })

  useEffect(() => {
    const controller = new AbortController()
    setResult({ phase: 'loading', envelope: null })

    apiClient.request(buildEastmoneyPath({ date, days }), { signal: controller.signal })
      .then((envelope) => {
        if (!controller.signal.aborted) {
          setResult({ phase: 'ready', envelope })
        }
      })
      .catch((error) => {
        if (controller.signal.aborted) return
        if (error.code === 'DATA_NOT_AVAILABLE' && error.envelope) {
          setResult({ phase: 'ready', envelope: error.envelope })
          return
        }
        setResult({ phase: 'error', envelope: null })
      })

    return () => controller.abort()
  }, [apiClient, date, days])

  return result
}
