/*
 * 日期控件应当显示的日期：用户手选优先，未手选时回落到后端返回的业务日期。
 *
 * 未手选日期时后端按"最近一个已发布交易日"取数，界面必须显示那一天 ——
 * 直接把空值传给控件只会显示占位文案「最新交易日」，用户看不到自己在看哪一天。
 * 四个页面共用这一个函数，避免某个页面漏掉回填（本项目已出现过三次只有
 * 板块资金流页显示具体日期、其余三页显示占位文案的情况）。
 */
export function resolveDisplayDate(selectedDate, envelope) {
  return selectedDate || envelope?.business_date || ''
}
