import { useEffect, useRef, useState } from 'react'

import { isTradingSession } from './marketSession'

/* `envelopeErrorCodes` 省略时的默认值。必须是模块级常量，理由见下方说明。 */
const DEFAULT_ENVELOPE_ERROR_CODES = ['DATA_NOT_AVAILABLE']

/*
 * 交易时段哨兵的重查间隔。与 `pollIntervalMs`（进入时段后的数据重取间隔）是两件
 * 不同的事：这个只管"现在还在不在交易时段"，所以固定 30 秒，不随页面配置变。
 */
const SESSION_CHECK_INTERVAL_MS = 30000

/*
 * 取数 + 盘中自动重取。
 *
 * 四个页面共用同一套行为：挂载或依赖变化时取一次，之后只要还落在交易时段内就
 * 按固定间隔重取。重取是"静默"的 —— 成功才替换数据，失败不会把已经渲染好的
 * 页面打回错误态，否则每半小时一次的刷新会让用户看到一次无谓的闪白。
 *
 * 页面在后台标签页时不重取：没人看的时候把请求省下来。
 *
 * `envelopeErrorCodes` 列出"应当带着响应正文渲染的 4xx 错误码"：后端把"这一天
 * 确实没有数据"表示成 404（HTTP 上是失败），但它对页面来说是一种**已知状态**
 * 而不是故障，所以由页面按 `error.code` 显示对应的空态/提示。传 null 表示
 * "页面对错误码有自己的处理，不要接管"。
 *
 * **它必须是模块级常量**（每个调用方都在自己的 `useXxx.js` 里导出这样一个数组，
 * 例如 `HUNDRED_DAY_ENVELOPE_ERROR_CODES`）：它直接进下面的依赖数组，每次渲染
 * 新建的字面量会换引用，让 effect 连同一次请求无限重跑。这里不再替调用方做
 * "内容指纹归一化" —— 那层防御只会把契约藏起来，代价是每个读者都要多追一层。
 */
export default function usePolledResource({
  apiClient,
  path,
  pollIntervalMs = 0,
  envelopeErrorCodes = DEFAULT_ENVELOPE_ERROR_CODES,
}) {
  const [state, setState] = useState({ phase: 'loading', envelope: null, refreshedAt: null })
  const requestIdRef = useRef(0)
  // 通过 ref 持有 client：调用方若每次渲染都新建一个 client 对象，把它写进依赖
  // 会让 effect（进而是一次请求）无限重跑。只有 path / 间隔变化才需要重来。
  // effect 里的 load() 读的就是 `apiClientRef.current`，所以登录态变化后新建的
  // client 会从下一次请求开始生效 —— 闭包里的 `apiClient` 不参与发请求。
  const apiClientRef = useRef(apiClient)
  apiClientRef.current = apiClient

  useEffect(() => {
    let disposed = false
    let controller = null
    let timer = null
    let idleTimer = null

    const load = ({ silent }) => {
      if (controller) {
        controller.abort()
      }
      controller = new AbortController()
      const requestId = requestIdRef.current + 1
      requestIdRef.current = requestId

      if (!silent) {
        setState({ phase: 'loading', envelope: null, refreshedAt: null })
      }

      apiClientRef.current.request(path, { signal: controller.signal })
        .then((envelope) => {
          if (disposed || requestId !== requestIdRef.current) return
          setState({ phase: 'ready', envelope, refreshedAt: Date.now() })
        })
        .catch((error) => {
          if (disposed || requestId !== requestIdRef.current || controller.signal.aborted) return
          if (envelopeErrorCodes?.includes(error.code) && error.envelope) {
            setState({ phase: 'ready', envelope: error.envelope, refreshedAt: Date.now() })
            return
          }
          if (silent) return
          setState({ phase: 'error', envelope: null, refreshedAt: null })
        })
    }

    load({ silent: false })

    // 按 SESSION_CHECK_INTERVAL_MS 重看一次“现在是否还在交易时段”：开盘瞬间打开
    // 页面的人也要能等到第一次自动刷新，而收盘后打开的页面不该白白养着一个定时器。
    if (pollIntervalMs > 0) {
      idleTimer = setInterval(() => {
        const active = isTradingSession()
        if (active && !timer) {
          timer = setInterval(() => {
            if (typeof document !== 'undefined' && document.hidden) return
            load({ silent: true })
          }, pollIntervalMs)
        } else if (!active && timer) {
          clearInterval(timer)
          timer = null
        }
      }, SESSION_CHECK_INTERVAL_MS)
    }

    return () => {
      disposed = true
      if (controller) controller.abort()
      if (timer) clearInterval(timer)
      if (idleTimer) clearInterval(idleTimer)
    }
    // apiClient 有意不进依赖数组：effect 内读的是 apiClientRef.current，把它列进来
    // 只会让调用方每次渲染新建 client 对象时白白重跑一次 effect（连带一次请求）。
  }, [path, pollIntervalMs, envelopeErrorCodes])

  return state
}
