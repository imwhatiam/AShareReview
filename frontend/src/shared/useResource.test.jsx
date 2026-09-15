import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import useResource from './useResource'

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

function deferred() {
  let resolve
  let reject
  const promise = new Promise((finish, fail) => {
    resolve = finish
    reject = fail
  })
  return { promise, resolve, reject }
}

describe('useResource', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  function renderResource({ request, path = '/api/resource/', ...rest }) {
    // 同一份 client 实例贯穿整个测试：调用方（四个页面）也是这么做的。
    const apiClient = { request }
    return renderHook(
      ({ currentPath }) => useResource({ apiClient, path: currentPath, ...rest }),
      { initialProps: { currentPath: path } },
    )
  }

  /*
   * 时间戳的语义是本次改造的核心：它必须是**信封里数据自己的时刻**，而不是请求
   * 发出的时刻。原样透传是唯一能钉住它的断言 —— 换成 Date.now() 这条就挂。
   */
  it('reports when the data was written, not when it was fetched', async () => {
    const request = vi.fn().mockResolvedValue({
      data: { value: 1 },
      data_updated_at: '2026-09-09T15:35:00+08:00',
    })

    const { result } = renderResource({ request })
    await flush()

    expect(result.current.phase).toBe('ready')
    expect(result.current.envelope.data.value).toBe(1)
    expect(result.current.updatedAt).toBe('2026-09-09T15:35:00+08:00')
    expect(request).toHaveBeenCalledTimes(1)
  })

  /*
   * 信封没有数据时刻时保持 null，绝不退化成"当前时间"：那种退化会让空态与刚取回的
   * 数据看起来一样新，正是这次要修掉的东西。
   */
  it('has no timestamp at all when the envelope carries no data time', async () => {
    const request = vi.fn().mockResolvedValue({ data: { value: 1 } })

    const { result } = renderResource({ request })
    await flush()

    expect(result.current.phase).toBe('ready')
    expect(result.current.updatedAt).toBeNull()
  })

  /*
   * 反轮询守卫：这是本次改造的核心不变量。页面自己**一次**都不许再发请求 ——
   * 原来那条按交易时段触发的定时器已删除，把两小时的时间推完也必须还是 1 次。
   */
  it('never fetches on its own, however long the page stays open', async () => {
    vi.useFakeTimers()
    const request = vi.fn().mockResolvedValue({ data: { value: 1 } })

    renderResource({ request })
    await flush()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2 * 60 * 60 * 1000)
    })

    expect(request).toHaveBeenCalledTimes(1)
  })

  it('fetches again when refresh() is called', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ data: { value: 1 } })
      .mockResolvedValueOnce({ data: { value: 2 } })

    const { result } = renderResource({ request })
    await flush()
    expect(request).toHaveBeenCalledTimes(1)

    await act(async () => {
      result.current.refresh()
    })
    await flush()

    expect(request).toHaveBeenCalledTimes(2)
    expect(result.current.envelope.data.value).toBe(2)
    expect(result.current.phase).toBe('ready')
  })

  it('cancels the request it replaces when refresh() lands mid-flight', async () => {
    const requests = []
    const request = vi.fn((path, options) => {
      const pending = deferred()
      requests.push({ path, options, ...pending })
      return pending.promise
    })

    const { result } = renderResource({ request })
    await waitFor(() => expect(requests).toHaveLength(1))

    act(() => result.current.refresh())
    await waitFor(() => expect(requests).toHaveLength(2))
    expect(requests[0].options.signal.aborted).toBe(true)
    expect(requests[1].options.signal.aborted).toBe(false)

    // 被取消的那次以 AbortError 落地时，不得把正在等新请求的页面打成错误态。
    requests[0].reject(new DOMException('The operation was aborted.', 'AbortError'))
    await flush()
    expect(result.current.phase).toBe('loading')

    requests[1].resolve({ data: { value: 2 } })
    await flush()
    expect(result.current.phase).toBe('ready')
    expect(result.current.envelope.data.value).toBe(2)
  })

  it('re-fetches when the path changes and abandons the late response', async () => {
    const first = deferred()
    const second = deferred()
    const request = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const { result, rerender } = renderResource({ request })
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))

    rerender({ currentPath: '/api/resource/?date=2026-09-08' })
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
    expect(request.mock.calls[1][0]).toBe('/api/resource/?date=2026-09-08')

    second.resolve({ data: { value: 'new' } })
    await flush()
    expect(result.current.envelope.data.value).toBe('new')

    // 晚到的旧响应绝不能盖掉当前选中的日期。
    first.resolve({ data: { value: 'old' } })
    await flush()
    expect(result.current.envelope.data.value).toBe('new')
  })

  /*
   * 手动刷新失败要**说出来**：这条与旧的"静默重取"正好相反，是本改造的显式决定，
   * 所以单独钉一条 —— 用户点了一下却什么都不显示（页面停在看似正常的数据上）
   * 是比"闪一下错误态"更糟的结果。
   */
  it('surfaces a failed refresh as an error instead of keeping the old data', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ data: { value: 1 } })
      .mockRejectedValueOnce(new Error('network down'))

    const { result } = renderResource({ request })
    await flush()
    expect(result.current.phase).toBe('ready')

    await act(async () => {
      result.current.refresh()
    })
    await flush()

    expect(request).toHaveBeenCalledTimes(2)
    expect(result.current.phase).toBe('error')
    expect(result.current.envelope).toBeNull()
    expect(result.current.updatedAt).toBeNull()
  })

  it('surfaces a first-load failure as an error state', async () => {
    const request = vi.fn().mockRejectedValue(new Error('network down'))

    const { result } = renderResource({ request })
    await flush()

    expect(result.current.phase).toBe('error')
    expect(result.current.envelope).toBeNull()
    expect(result.current.updatedAt).toBeNull()
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
})
