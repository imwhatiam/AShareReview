import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import useHundredDay from './hundred-day/useHundredDay'
import useKaipanlaData, { buildKaipanlaPath } from './kaipanla/useKaipanlaData'
import useSectorMomentum from './sector-momentum/useSectorMomentum'
import useStockMoves from './stock-moves/useStockMoves'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((finish, fail) => {
    resolve = finish
    reject = fail
  })
  return { promise, resolve, reject }
}

function response(tradeDate) {
  return {
    status: 'ok', business_date: tradeDate, data_version: `hundred-day:${tradeDate}`,
    stale: false, warnings: [], data: { trade_date: tradeDate },
  }
}

/*
 * 四个页面的取数 hook 都是 `usePolledResource` 的薄包装，差别只在三处：请求路径、
 * 轮询间隔、"哪些 4xx 要带正文渲染"。取数语义（取消上一个请求、丢弃过期响应、
 * 静默重取）只在共享层实现一次。
 *
 * 所以这里**按同一套不变量把四个页面逐个走一遍**，而不是只测其中一个：
 * 单页用例里，某个页面把 `date` 接错、漏进依赖数组、或者路径拼错，都不会有
 * 任何症状 —— 它照样能加载出数据，只是在切日期时留下一个悬空请求。
 * 只有"每个页面都必须满足"的断言才能发现这种漏接。
 *
 * `useKaipanlaData` 多一个 `days` 参数，统一传 1（单日视图）。
 *
 * 三个按日期取数的页面，期望路径写成**字面量**而不是调用生产代码里的构造函数：
 * "页面请求的是这个 URL"才是要守的契约，拿构造函数算期望值时，构造函数自己写错
 * 也照样全绿。资金流页有查询串（`days` / 榜单条数），仍由它自己的构造函数给出。
 */
const PAGES = [
  {
    name: '百日新高',
    usePage: useHundredDay,
    paths: { none: '/api/hundred-day/', dated: '/api/hundred-day/?date=2026-09-08' },
  },
  {
    name: '个股异动',
    usePage: useStockMoves,
    paths: { none: '/api/stock-moves/', dated: '/api/stock-moves/?date=2026-09-08' },
  },
  {
    name: '板块动量',
    usePage: useSectorMomentum,
    paths: {
      none: '/api/sector-momentum/',
      dated: '/api/sector-momentum/?date=2026-09-08',
    },
  },
  {
    name: '板块资金流',
    usePage: useKaipanlaData,
    paths: {
      none: buildKaipanlaPath({ date: '', days: 1 }),
      dated: buildKaipanlaPath({ date: '2026-09-08', days: 1 }),
    },
  },
]

describe('feature request integration', () => {
  for (const page of PAGES) {
    describe(page.name, () => {
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
          ({ date }) => page.usePage({ apiClient, date, days: 1 }),
          { initialProps: { date: '' } },
        )

        rerender({ date: '2026-09-08' })
        rerender({ date: '2026-09-07' })
        newerSelection.resolve(response('2026-09-07'))
        await waitFor(() => expect(result.current.envelope?.business_date).toBe('2026-09-07'))

        // 两个更早的请求现在才落地：晚到的旧响应绝不能盖掉当前选中的日期。
        olderSelection.resolve(response('2026-09-08'))
        initial.resolve(response('2026-09-09'))
        await Promise.resolve()
        expect(result.current.envelope?.business_date).toBe('2026-09-07')
      })

      it('cancels the in-flight request instead of leaving it dangling', async () => {
        const requests = []
        const apiClient = {
          request: vi.fn((path, options) => {
            const pending = deferred()
            requests.push({ path, options, ...pending })
            return pending.promise
          }),
        }
        const { result, rerender, unmount } = renderHook(
          ({ date }) => page.usePage({ apiClient, date, days: 1 }),
          { initialProps: { date: '' } },
        )

        await waitFor(() => expect(requests).toHaveLength(1))
        expect(requests[0].path).toBe(page.paths.none)
        expect(requests[0].options.signal.aborted).toBe(false)

        rerender({ date: '2026-09-08' })
        await waitFor(() => expect(requests).toHaveLength(2))
        expect(requests[1].path).toBe(page.paths.dated)

        /*
         * 切日期必须真的把上一个请求取消掉，而不是"发了新的、旧的随它去"：
         * 旧连接不释放，慢响应回来时还会走一遍 `.then`；共享层挡过期响应靠的
         * 就是 `signal.aborted` 这道闸。这里第一次把它钉住 —— 在此之前整个前端
         * 测试里没有任何一条断言检查过 abort 是否真的发生。
         */
        expect(requests[0].options.signal.aborted).toBe(true)
        expect(requests[1].options.signal.aborted).toBe(false)

        // 被取消的请求以 AbortError 落地时，不得把正在等新请求的页面打成错误态。
        requests[0].reject(new DOMException('The operation was aborted.', 'AbortError'))
        await act(async () => {
          await Promise.resolve()
        })
        expect(result.current.phase).toBe('loading')

        // 离开页面同样要取消：否则用户切走之后，请求还挂在网络上。
        unmount()
        expect(requests[1].options.signal.aborted).toBe(true)
      })
    })
  }
})
