import usePolledResource from './usePolledResource'

/*
 * 盘中每 30 分钟自动重取，与 `refresh_intraday_quotes` 的采集节奏一致 ——
 * 百日新高新低 / 板块动量 / 个股异动三个页面共用这一个节奏。
 */
export const INTRADAY_POLL_INTERVAL_MS = 30 * 60 * 1000

/*
 * 按业务日期取当天结果。未手选日期时才轮询：用户翻看历史某天时不该被自动刷新打断。
 *
 * 三个页面此前各写了一份同样的 hook —— 连上面两行说明都是逐字复制的三份，只差
 * 端点与错误码清单。那两样是各模块自己声明的契约（连带"哪些 4xx 要带正文渲染、
 * 为什么"的理由），所以留在各自的 `useXxx.js` 里；取数语义只在这一处实现。
 *
 * `envelopeErrorCodes` 必须是模块级常量，见 `usePolledResource` 的说明。
 */
export default function useDateResource({ apiClient, date, basePath, envelopeErrorCodes }) {
  return usePolledResource({
    apiClient,
    path: date ? `${basePath}?date=${date}` : basePath,
    pollIntervalMs: date ? 0 : INTRADAY_POLL_INTERVAL_MS,
    envelopeErrorCodes,
  })
}
