import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import useHundredDay from './hundred-day/useHundredDay'

function deferred() {
  let resolve
  const promise = new Promise((finish) => { resolve = finish })
  return { promise, resolve }
}

function response(tradeDate) {
  return {
    status: 'ok', business_date: tradeDate, data_version: `hundred-day:${tradeDate}`,
    stale: false, warnings: [], data: { trade_date: tradeDate },
  }
}

describe('feature request integration', () => {
  it('does not let an older date response overwrite the newer date selection', async () => {
    const initial = deferred()
    const olderSelection = deferred()
    const newerSelection = deferred()
    const apiClient = {
      request: vi.fn()
        .mockReturnValueOnce(initial.promise)
        .mockReturnValueOnce(olderSelection.promise)
        .mockReturnValueOnce(newerSelection.promise),
    }
    const { result, rerender } = renderHook(
      ({ date }) => useHundredDay({ apiClient, date }),
      { initialProps: { date: '' } },
    )

    rerender({ date: '2026-09-08' })
    rerender({ date: '2026-09-07' })
    newerSelection.resolve(response('2026-09-07'))
    await waitFor(() => expect(result.current.envelope?.business_date).toBe('2026-09-07'))

    olderSelection.resolve(response('2026-09-08'))
    initial.resolve(response('2026-09-09'))
    await Promise.resolve()
    expect(result.current.envelope?.business_date).toBe('2026-09-07')
  })
})
