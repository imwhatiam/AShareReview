import { describe, expect, it, vi } from 'vitest'

import { ApiClientError, createApiClient } from './client'


describe('createApiClient', () => {
  it('uses a same-origin session, sends CSRF for a mutation, and returns the response envelope', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: 'partial', data: { rows: [] }, warnings: ['部分数据'],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const client = createApiClient({ fetchImpl, getCsrfToken: () => 'csrf-token' })

    const result = await client.request('/api/example/', {
      method: 'POST', body: { date: '2026-09-08' },
    })

    expect(fetchImpl).toHaveBeenCalledWith('/api/example/', expect.objectContaining({
      method: 'POST', credentials: 'same-origin', signal: undefined,
      headers: expect.objectContaining({
        'Content-Type': 'application/json', 'X-CSRFToken': 'csrf-token',
      }),
      body: JSON.stringify({ date: '2026-09-08' }),
    }))
    expect(result.status).toBe('partial')
    expect(result.warnings).toEqual(['部分数据'])
  })

  it('keeps a 202 preparing envelope available to the page', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: 'preparing', error: { code: 'DATA_PREPARING', message: '正在准备' },
    }), { status: 202, headers: { 'Content-Type': 'application/json' } }))
    const client = createApiClient({ fetchImpl })

    await expect(client.request('/api/example/')).resolves.toMatchObject({
      status: 'preparing', error: { code: 'DATA_PREPARING' },
    })
  })

  it('notifies the app and exposes the standardized error for an expired session', async () => {
    const onUnauthorized = vi.fn()
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: 'error', error: { code: 'AUTH_REQUIRED', message: '请先登录。' },
    }), { status: 401, headers: { 'Content-Type': 'application/json' } }))
    const client = createApiClient({ fetchImpl, onUnauthorized })

    await expect(client.request('/api/example/')).rejects.toEqual(expect.objectContaining({
      name: 'ApiClientError', status: 401, code: 'AUTH_REQUIRED',
    }))
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('forwards the caller signal and lets a cancellation through unwrapped', async () => {
    const controller = new AbortController()
    const abortError = new DOMException('The operation was aborted.', 'AbortError')
    const fetchImpl = vi.fn().mockImplementation(() => Promise.reject(abortError))
    const client = createApiClient({ fetchImpl })

    controller.abort()

    /*
     * 取消必须原样抛出，**不能**被包成 ApiClientError。`useResource` 区分
     * "用户切了日期、上一次请求被主动取消"（什么都不做）和"请求真的失败了"
     * （渲染错误态），靠的就是"它不是 ApiClientError 且 signal 已 aborted"这两点；
     * 包一层会让每次快速切日期都闪一下错误页。
     */
    await expect(
      client.request('/api/example/', { signal: controller.signal }),
    ).rejects.toBe(abortError)
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/example/',
      expect.objectContaining({ signal: controller.signal }),
    )
  })

  it('maps a server failure without a JSON body to a standardized error', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(
      '<html><body>502 Bad Gateway</body></html>',
      { status: 502, headers: { 'Content-Type': 'text/html' } },
    ))
    const client = createApiClient({ fetchImpl })

    // 解析失败不能变成 JSON 解析异常冒到页面上：状态码要留住，错误码要说清是
    // "响应本身不合法"。反代返回 HTML 错误页在部署里很常见。
    await expect(client.request('/api/example/')).rejects.toEqual(expect.objectContaining({
      name: 'ApiClientError', status: 502, code: 'INVALID_RESPONSE',
    }))
  })

  it('returns the invalid-response envelope when a 200 body is not JSON', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(
      '<!doctype html><html></html>',
      { status: 200, headers: { 'Content-Type': 'text/html' } },
    ))
    const client = createApiClient({ fetchImpl })

    // 200 + 非 JSON：HTTP 上是成功，但拿不到信封。返回一个 status=error 的信封，
    // 而不是抛错 —— 调用方按 `error.code` 走空态/失败判断比按异常类型判断稳。
    await expect(client.request('/api/example/')).resolves.toEqual({
      status: 'error',
      error: { code: 'INVALID_RESPONSE', message: '服务返回了无效响应。' },
    })
  })

  it('does not call the unauthorized hook for a 404 or a 500', async () => {
    const onUnauthorized = vi.fn()
    const fetchImpl = vi.fn(async (path) => new Response(
      JSON.stringify({ status: 'error', error: { code: 'REQUEST_FAILED', message: '失败' } }),
      { status: path === '/api/missing/' ? 404 : 500, headers: { 'Content-Type': 'application/json' } },
    ))
    const client = createApiClient({ fetchImpl, onUnauthorized })

    await expect(client.request('/api/missing/')).rejects.toBeInstanceOf(ApiClientError)
    await expect(client.request('/api/broken/')).rejects.toBeInstanceOf(ApiClientError)

    // 只有 401 才算登录失效；把 5xx 也当成登录失效会把用户踢回登录页并丢掉现场。
    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})
