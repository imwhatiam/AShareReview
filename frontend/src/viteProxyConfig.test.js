import { describe, expect, it } from 'vitest'

import { createDevelopmentApiProxy } from './api/developmentProxy'

/*
 * 开发代理只有一个开关作用：`.env` 里配了后端 origin 就把 `/api` 转过去，没配就
 * 完全不注册代理（请求打到 Vite 自己身上、拿到 404），而不是带着空 target 去转发。
 * 后者会让 `vite dev` 启动即失败，或者把请求送去一个意想不到的地址。
 */
describe('development API proxy', () => {
  it('forwards API requests to the configured Django backend origin', () => {
    expect(createDevelopmentApiProxy('http://127.0.0.1:8000')).toEqual({
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    })
  })

  it('registers no proxy at all when the origin is missing or blank', () => {
    // "没配置"有三种写法，都必须落进同一个分支：缺失、空串、只有空白。
    for (const origin of [undefined, null, '', '   ']) {
      expect(createDevelopmentApiProxy(origin)).toEqual({})
    }
  })

  it('trims the configured origin before using it as a target', () => {
    // .env 里多打一个空格很常见；原样拿去当 target 就不是合法地址了。
    expect(createDevelopmentApiProxy('  http://127.0.0.1:8000  ')).toEqual({
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    })
  })
})
