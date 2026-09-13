import { describe, expect, it } from 'vitest'

import { resolveDataStateName } from './dataStateName'

function envelope(overrides = {}) {
  return { status: 'ok', data: {}, ...overrides }
}

describe('resolveDataStateName', () => {
  it('reports the loading and error phases before looking at the payload', () => {
    expect(resolveDataStateName('loading', null)).toBe('loading')
    expect(resolveDataStateName('error', null)).toBe('error')
    // 阶段优先：即使正文里带着错误码，失败相位也不该被降级成空态。
    expect(resolveDataStateName('error', envelope({ error: { code: 'DATA_NOT_AVAILABLE' } })))
      .toBe('error')
  })

  /*
   * 202 与 409 都是"稍后会有"，不是失败。把它们映射到 preparing 之后，
   * 页面才不会在数据集正在生成时显示"数据暂时无法加载"。
   */
  it.each([['DATA_PREPARING'], ['SYNC_IN_PROGRESS']])(
    'treats %s as a retryable preparing state',
    (code) => {
      expect(resolveDataStateName('ready', envelope({ status: 'error', error: { code } })))
        .toBe('preparing')
    },
  )

  it('treats a missing explicit date as empty, not as preparing', () => {
    expect(resolveDataStateName('ready', envelope(), { hasContent: false })).toBe('empty')
    // 带正文的 404 同样是空态，页面据此显示"这天没有数据"。
    expect(resolveDataStateName(
      'ready',
      envelope({ status: 'error', error: { code: 'DATA_NOT_AVAILABLE' } }),
      { hasContent: false },
    )).toBe('empty')
  })

  /*
   * 页面专属的"没有数据"错误码（如百日新高的 INSUFFICIENT_HISTORY）要显式声明：
   * 声明之后它就是空态，比"正文里恰好没有 data"这个巧合更可靠。
   */
  it('lets a page classify extra codes as empty', () => {
    const payload = envelope({
      status: 'error', error: { code: 'INSUFFICIENT_HISTORY' }, data: { totals: {} },
    })

    expect(resolveDataStateName('ready', payload)).toBeNull()
    expect(resolveDataStateName('ready', payload, { emptyCodes: ['INSUFFICIENT_HISTORY'] }))
      .toBe('empty')
  })

  it('returns null only when there is something to render', () => {
    expect(resolveDataStateName('ready', envelope())).toBeNull()
    expect(resolveDataStateName('ready', null)).toBe('empty')
    expect(resolveDataStateName('ready', envelope(), { hasContent: false })).toBe('empty')
  })
})
