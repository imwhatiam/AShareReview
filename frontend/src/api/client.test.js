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

  it('preserves caller cancellation and standardizes non-2xx API errors', async () => {
    const controller = new AbortController()
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: 'error', error: { code: 'DATA_NOT_AVAILABLE', message: '无数据' },
    }), { status: 404, headers: { 'Content-Type': 'application/json' } }))
    const client = createApiClient({ fetchImpl })

    await expect(client.request('/api/example/', { signal: controller.signal })).rejects
      .toBeInstanceOf(ApiClientError)
    expect(fetchImpl).toHaveBeenCalledWith('/api/example/', expect.objectContaining({
      signal: controller.signal,
    }))
  })
})
