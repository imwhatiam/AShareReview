import { useCallback, useEffect, useRef, useState } from 'react'

/* `envelopeErrorCodes` 省略时的默认值。必须是模块级常量，理由见下方说明。 */
const DEFAULT_ENVELOPE_ERROR_CODES = ['DATA_NOT_AVAILABLE']

/*
 * 取数：挂载取一次，`path` 变化（换日期、换统计窗口）再取一次，调用方还可以主动
 * 调 `refresh()` 再取一次 —— 工具栏那颗「更新于 HH:MM」就是它唯一的入口。
 *
 * **这里没有定时器：页面永远不会自己发请求。** 2026-09-14 之前它按交易时段做盘中
 * 自动重取（资金流 5 分钟、其余三页 30 分钟，靠 `marketSession.js` 判时段），现在
 * 整条自动链路已删除 —— 什么时候拿新数据由用户点那颗胶囊决定。
 *
 * 每次取数都会取消上一个在途请求，再用 `requestId` 丢弃晚到的响应：用户快速切日期
 * 时，先发的那次请求回来晚了也不能盖掉当前选中的日期。
 *
 * 主动 `refresh()` 与切日期走的是完全相同的一次加载：期间显示加载态，失败显示错误
 * 态。这是刻意的 —— 用户点了一下就该看到"正在取数"或"取失败"，而不是毫无反应。
 * 原来那条"静默重取"（成功才替换数据、失败保留旧页面）只服务于定时轮询，怕每半
 * 小时闪白一次；手动触发没有这个问题，也不需要一套额外的状态。
 *
 * `updatedAt` 是**这份数据写进数据库的时刻**（信封的 `data_updated_at`），不是"这次
 * 请求是几点发的"。用户看它的目的是判断"屏幕上的数字有多新"，所以它必须来自数据
 * 自己：结果行落库之后一直躺在那儿，页面随时打开，两者可以差好几个小时。服务端没
 * 给出这个时刻时（该日期确实没有数据）它保持 null，胶囊交给调用方决定渲不渲染。
 *
 * `envelopeErrorCodes` 列出"应当带着响应正文渲染的 4xx 错误码"：后端把"这一天
 * 确实没有数据"表示成 404（HTTP 上是失败），但它对页面来说是一种**已知状态**
 * 而不是故障，所以由页面按 `error.code` 显示对应的空态/提示。传 null 表示
 * "页面对错误码有自己的处理，不要接管"。
 *
 * **它必须是模块级常量**（每个调用方都在自己的 `useXxx.js` 里定义这样一个数组，
 * 例如 `HUNDRED_DAY_ENVELOPE_ERROR_CODES`）：它直接进下面的依赖数组，每次渲染
 * 新建的字面量会换引用，让 effect 连同一次请求无限重跑。这里不再替调用方做
 * "内容指纹归一化" —— 那层防御只会把契约藏起来，代价是每个读者都要多追一层。
 */
export default function useResource({
  apiClient,
  path,
  envelopeErrorCodes = DEFAULT_ENVELOPE_ERROR_CODES,
}) {
  const [state, setState] = useState({ phase: 'loading', envelope: null, updatedAt: null })
  /*
   * 手动刷新的令牌：+1 就等于"再取一次"。用 state 而不是把 effect 里的 `load()`
   * 抛出去，是为了让"取消在途请求 + 丢弃过期响应"这套语义只存在于 effect 一处。
   */
  const [reloadToken, setReloadToken] = useState(0)
  const requestIdRef = useRef(0)
  // 通过 ref 持有 client：调用方若每次渲染都新建一个 client 对象，把它写进依赖
  // 会让 effect（进而是一次请求）无限重跑。只有 path / 刷新令牌变化才需要重来。
  // effect 里的 load() 读的就是 `apiClientRef.current`，所以登录态变化后新建的
  // client 会从下一次请求开始生效 —— 闭包里的 `apiClient` 不参与发请求。
  const apiClientRef = useRef(apiClient)
  apiClientRef.current = apiClient

  useEffect(() => {
    let disposed = false
    let controller = null

    const load = () => {
      if (controller) {
        controller.abort()
      }
      controller = new AbortController()
      const requestId = requestIdRef.current + 1
      requestIdRef.current = requestId

      setState({ phase: 'loading', envelope: null, updatedAt: null })

      apiClientRef.current.request(path, { signal: controller.signal })
        .then((envelope) => {
          if (disposed || requestId !== requestIdRef.current) return
          setState({
            phase: 'ready',
            envelope,
            updatedAt: envelope.data_updated_at ?? null,
          })
        })
        .catch((error) => {
          if (disposed || requestId !== requestIdRef.current || controller.signal.aborted) return
          if (envelopeErrorCodes?.includes(error.code) && error.envelope) {
            // 空态信封（这一天没有数据）里没有数据时刻，`updatedAt` 保持 null ——
            // 那个时刻描述的是"库里的数据"，没有数据就没有它。
            setState({
              phase: 'ready',
              envelope: error.envelope,
              updatedAt: error.envelope.data_updated_at ?? null,
            })
            return
          }
          setState({ phase: 'error', envelope: null, updatedAt: null })
        })
    }

    load()

    return () => {
      disposed = true
      if (controller) controller.abort()
    }
    // apiClient 有意不进依赖数组：effect 内读的是 apiClientRef.current，把它列进来
    // 只会让调用方每次渲染新建 client 对象时白白重跑一次 effect（连带一次请求）。
  }, [path, reloadToken, envelopeErrorCodes])

  const refresh = useCallback(() => {
    setReloadToken((token) => token + 1)
  }, [])

  return {
    phase: state.phase,
    envelope: state.envelope,
    updatedAt: state.updatedAt,
    refresh,
  }
}
