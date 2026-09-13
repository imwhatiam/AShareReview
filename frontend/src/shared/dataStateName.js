/*
 * 把「取数阶段 + 响应正文」翻译成内容区该显示的 DataState 状态名，四个页面共用。
 *
 * 关键约定：返回值描述的是**内容区**（图表 / 榜单 / 看板 / 统计行）该显示什么，
 * 而不是整页该显示什么。页面外壳 —— 日期控件、统计窗口按钮、刷新时间戳 —— 在
 * 任何状态下都必须保持挂载，否则用户刚在日期控件里选完一天，控件就被卸载重建：
 * 页面先塌成一行提示再弹回原状，弹层展开的月份、键盘焦点、滚动位置全部丢失，
 * 用户还会以为页面出错了。
 *
 * 只有在**连外壳都给不出**时页面才整体替换；本项目的四个页面都不属于这种情况。
 *
 * 各错误码的含义（与后端 core/api/errors.py 对齐）：
 * - DATA_PREPARING（202）：请求没带日期且当天结果还没生成完，重试即可自愈。
 * - SYNC_IN_PROGRESS（409）：该日期的数据集正被另一轮采集占用，且连旧结果都没有。
 *   两者都是"稍后会有"，因此都映射到 preparing，而不是失败。
 * - DATA_NOT_AVAILABLE（404）：显式指定的日期确实没有数据，永远不会自愈 → empty。
 *
 * 返回 null 表示"有内容可渲染"。
 */

const PREPARING_CODES = new Set(['DATA_PREPARING', 'SYNC_IN_PROGRESS'])

export function resolveDataStateName(
  phase,
  envelope,
  { hasContent = true, emptyCodes = [] } = {},
) {
  if (phase === 'loading') return 'loading'
  if (phase === 'error') return 'error'
  // ready 却没有正文是不可能的组合；按空态处理，免得页面拿 null 去解构。
  if (!envelope) return 'empty'

  const code = envelope?.error?.code
  if (code && PREPARING_CODES.has(code)) return 'preparing'
  if (code === 'DATA_NOT_AVAILABLE' || emptyCodes.includes(code)) return 'empty'

  return hasContent ? null : 'empty'
}
