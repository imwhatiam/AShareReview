const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE'])

export class ApiClientError extends Error {
  constructor({ status, code, message, envelope }) {
    super(message)
    this.name = 'ApiClientError'
    this.status = status
    this.code = code
    this.envelope = envelope
  }
}

function readCookie(name) {
  if (typeof document === 'undefined') {
    return null
  }
  const prefix = `${encodeURIComponent(name)}=`
  return document.cookie.split(';').map((value) => value.trim()).find(
    (value) => value.startsWith(prefix),
  )?.slice(prefix.length) ?? null
}

function defaultGetCsrfToken() {
  return readCookie('csrftoken')
}

async function parseEnvelope(response) {
  try {
    return await response.json()
  } catch {
    return {
      status: 'error',
      error: { code: 'INVALID_RESPONSE', message: '服务返回了无效响应。' },
    }
  }
}

export function createApiClient({
  fetchImpl = globalThis.fetch,
  getCsrfToken = defaultGetCsrfToken,
  onUnauthorized = () => {},
} = {}) {
  if (typeof fetchImpl !== 'function') {
    throw new TypeError('A fetch implementation is required.')
  }

  async function request(
      path,
      { method = 'GET', body, headers = {}, signal, notifyUnauthorized = true } = {},
    ) {
    const normalizedMethod = method.toUpperCase()
    const requestHeaders = { ...headers }
    const options = {
      method: normalizedMethod,
      credentials: 'same-origin',
      headers: requestHeaders,
      signal,
    }
    if (body !== undefined) {
      requestHeaders['Content-Type'] ??= 'application/json'
      options.body = JSON.stringify(body)
    }
    if (!SAFE_METHODS.has(normalizedMethod)) {
      const csrfToken = getCsrfToken()
      if (csrfToken) {
        requestHeaders['X-CSRFToken'] ??= csrfToken
      }
    }

    const response = await fetchImpl(path, options)
    const envelope = await parseEnvelope(response)
    if (response.status === 401 && notifyUnauthorized) {
      onUnauthorized(envelope)
    }
    if (!response.ok && response.status !== 202) {
      throw new ApiClientError({
        status: response.status,
        code: envelope.error?.code ?? 'REQUEST_FAILED',
        message: envelope.error?.message ?? '请求失败。',
        envelope,
      })
    }
    return envelope
  }

  return { request }
}
