import useResource from './useResource'

/*
 * 按业务日期取当天结果。
 *
 * 三个页面此前各写了一份同样的 hook —— 连说明都是逐字复制的三份，只差端点与错误码
 * 清单。那两样是各模块自己声明的契约（连带"哪些 4xx 要带正文渲染、为什么"的理由），
 * 所以留在各自的 `useXxx.js` 里；取数语义只在这一处实现。
 *
 * `envelopeErrorCodes` 必须是模块级常量，见 `useResource` 的说明。
 */
export default function useDateResource({ apiClient, date, basePath, envelopeErrorCodes }) {
  return useResource({
    apiClient,
    path: date ? `${basePath}?date=${date}` : basePath,
    envelopeErrorCodes,
  })
}
