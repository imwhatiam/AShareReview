/*
 * 展示层的统一数字写法。
 *
 * 起点是"个股"：三个页面（个股看板 / 板块动量 / 百日新高新低）都要在行业明细里
 * 列个股，涨跌幅与成交额的格式必须一致，否则同一只股票在不同页面上会写成两个
 * 样子。后来页面级的比率、评分、全市场成交额也一并收到这里 —— **全站的两位小数、
 * 百分号、单位换算只能有这一份实现**。
 *
 * 缺失值（null / undefined / 空字符串 / 非数字）一律留破折号。这层判断不是装饰：
 * `Number('')`、`Number(null)` 都是 0，少了它会安静地显示成 `0.00%`，看上去像
 * 平盘；而 `Number(undefined).toFixed(2)` 会显示成 `NaN` 并把整行数字变成噪音。
 */

/* 能安全参与算术的值返回 number，其余返回 null。 */
function toNumber(value) {
  if (value == null || value === '') {
    return null
  }
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

/* 定点小数：`formatDecimal(1.23456, 4)` → `1.2346`。 */
export function formatDecimal(value, digits = 2) {
  const number = toNumber(value)
  return number === null ? '—' : number.toFixed(digits)
}

/* 比率转百分号：`0.0523` → `5.23%`。 */
export function formatRatioPercent(value) {
  const number = toNumber(value)
  return number === null ? '—' : `${(number * 100).toFixed(2)}%`
}

/* 涨跌幅：正数带 +，保留两位小数；没有当日行情时留破折号。 */
export function formatChangePercent(value) {
  const number = toNumber(value)
  if (number === null) {
    return '—'
  }
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

/* 成交额：后端单位是元，换算成亿，**不带单位后缀**（调用方自己拼）。 */
export function formatTurnoverInYi(value) {
  const number = toNumber(value)
  return number === null ? '—' : (number / 1e8).toFixed(2)
}

/* 成交额带后缀，用在个股明细里。 */
export function formatTurnover(value) {
  const text = formatTurnoverInYi(value)
  return text === '—' ? '—' : `${text}亿`
}

/*
 * 净流入金额：正数带 +，一位小数，单位亿（与个股成交额同族，只是精度不同）。
 *
 * **缺失值返回 `null` 而不是破折号** —— 折线右端的常驻标签要靠"到底有没有值"决定
 * 要不要拼这一截，拼上破折号会变成「板块名 —」；榜单行则把 `null` 显示成破折号。
 * 写法只有这一份，两处呈现不同的只是"没有值的时候画什么"。
 */
export function formatFlowAmount(value) {
  const number = toNumber(value)
  return number === null ? null : `${number > 0 ? '+' : ''}${number.toFixed(1)}亿`
}

/* 一行写完一只股票：名称（涨幅，成交额）。 */
export function stockLabel(stock) {
  return `${stock.name}（${formatChangePercent(stock.change_percent)}，${formatTurnover(stock.turnover)}）`
}
