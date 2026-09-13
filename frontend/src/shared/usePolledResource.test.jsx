import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { isTradingSession } from './marketSession'
import usePolledResource from './usePolledResource'


vi.mock('./marketSession', () => ({
  isTradingSession: vi.fn(() => true),
}))

const POLL_MS = 5 * 60 * 1000
const SESSION_CHECK_MS = 30000

/*
 * `envelopeErrorCodes` 是 effect 的依赖之一，契约要求它是**稳定引用**（生产调用方
 * 都传自己模块里的导出常量）。写成内联字面量会每次渲染都换引用，把 effect 连同
 * 一次请求变成无限循环 —— 这个 fixture 因此必须提到模块级。
 */
const LISTED_CODES = ['DATA_NOT_AVAILABLE', 'INSUFFICIENT_HISTORY']

/* 首次加载是同步发起的，等一个微任务队列即可看到 ready。 */
async function flush() {
  await act(async () => {
    await Promise.resolve()
  })
}

async function advance(ms) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('usePolledResource', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    isTradingSession.mockReturnValue(true)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  function renderResource({ request, path = '/api/resource/', pollIntervalMs = POLL_MS, ...rest }) {
    // 同一份 client 实例贯穿整个测试：调用方（四个页面）也是这么做的。
    const apiClient = { request }
    return renderHook(() =>
      usePolledResource({ apiClient, path, pollIntervalMs, ...rest }),
    )
  }

  it('loads once and records when the data was fetched', async () => {
    const request = vi.fn().mockResolvedValue({ data: { value: 1 } })

    const { result } = renderResource({ request })
    await flush()

    expect(result.current.phase).toBe('ready')
    expect(result.current.envelope.data.value).toBe(1)
    expect(result.current.refreshedAt).not.toBeNull()
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('re-fetches on the configured interval during a trading session', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ data: { value: 1 } })
      .mockResolvedValueOnce({ data: { value: 2 } })

    const { result } = renderResource({ request })
    await flush()
    expect(request).toHaveBeenCalledTimes(1)

    await advance(SESSION_CHECK_MS + POLL_MS)

    expect(request).toHaveBeenCalledTimes(2)
    expect(result.current.envelope.data.value).toBe(2)
    expect(result.current.phase).toBe('ready')
  })

  it('does not poll outside the trading session', async () => {
    isTradingSession.mockReturnValue(false)
    const request = vi.fn().mockResolvedValue({ data: { value: 1 } })

    renderResource({ request })
    await flush()
    await advance(SESSION_CHECK_MS + POLL_MS * 3)

    expect(request).toHaveBeenCalledTimes(1)
  })

  it('stops polling once the session ends', async () => {
    const request = vi.fn().mockResolvedValue({ data: { value: 1 } })

    renderResource({ request })
    await flush()
    await advance(SESSION_CHECK_MS + POLL_MS)
    expect(request).toHaveBeenCalledTimes(2)

    isTradingSession.mockReturnValue(false)
    await advance(SESSION_CHECK_MS + POLL_MS * 3)

    expect(request).toHaveBeenCalledTimes(2)
  })

  it('keeps the rendered data when a background refresh fails', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ data: { value: 1 } })
      .mockRejectedValueOnce(new Error('network down'))

    const { result } = renderResource({ request })
    await flush()
    await advance(SESSION_CHECK_MS + POLL_MS)

    expect(request).toHaveBeenCalledTimes(2)
    expect(result.current.phase).toBe('ready')
    expect(result.current.envelope.data.value).toBe(1)
  })

  it('surfaces a first-load failure as an error state', async () => {
    const request = vi.fn().mockRejectedValue(new Error('network down'))

    const { result } = renderResource({ request })
    await flush()

    expect(result.current.phase).toBe('error')
    expect(result.current.envelope).toBeNull()
    expect(result.current.refreshedAt).toBeNull()
  })

  it('renders a missing date as ready when the caller opts in', async () => {
    const envelope = { status: 'error', error: { code: 'DATA_NOT_AVAILABLE' } }
    const request = vi.fn().mockRejectedValue(
      Object.assign(new Error('missing'), { code: 'DATA_NOT_AVAILABLE', envelope }),
    )

    const { result } = renderResource({ request })
    await flush()

    expect(result.current.phase).toBe('ready')
    expect(result.current.envelope).toBe(envelope)
  })

  it('keeps a missing date as an error when the caller opts out', async () => {
    const envelope = { status: 'error', error: { code: 'DATA_NOT_AVAILABLE' } }
    const request = vi.fn().mockRejectedValue(
      Object.assign(new Error('missing'), { code: 'DATA_NOT_AVAILABLE', envelope }),
    )

    const { result } = renderResource({ request, envelopeErrorCodes: null })
    await flush()

    expect(result.current.phase).toBe('error')
  })

  it('renders the envelope for every code the caller listed', async () => {
    const envelope = { status: 'error', error: { code: 'INSUFFICIENT_HISTORY' } }
    const request = vi.fn().mockRejectedValue(
      Object.assign(new Error('not enough history'), {
        code: 'INSUFFICIENT_HISTORY',
        envelope,
      }),
    )

    const { result } = renderResource({ request, envelopeErrorCodes: LISTED_CODES })
    await flush()

    expect(result.current.phase).toBe('ready')
    expect(result.current.envelope).toBe(envelope)
  })

  it('never polls when no interval is configured', async () => {
    const request = vi.fn().mockResolvedValue({ data: { value: 1 } })

    renderResource({ request, pollIntervalMs: 0 })
    await flush()
    await advance(SESSION_CHECK_MS * 10)

    expect(request).toHaveBeenCalledTimes(1)
  })
})
