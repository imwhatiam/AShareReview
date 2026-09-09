import { useEffect, useState } from 'react'

export function buildSectorMomentumPath(date) {
  return date ? `/api/sector-momentum/?date=${date}` : '/api/sector-momentum/'
}

export default function useSectorMomentum({ apiClient, date }) {
  const [result, setResult] = useState({ phase: 'loading', envelope: null })

  useEffect(() => {
    const controller = new AbortController()
    setResult({ phase: 'loading', envelope: null })
    apiClient.request(buildSectorMomentumPath(date), { signal: controller.signal })
      .then((envelope) => {
        if (!controller.signal.aborted) setResult({ phase: 'ready', envelope })
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
  }, [apiClient, date])

  return result
}
