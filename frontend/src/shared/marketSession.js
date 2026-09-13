/*
 * 盘中自动刷新的时间判定。
 *
 * 只覆盖连续竞价时段：周一至周五 09:30-11:30 与 13:00-15:00。节假日不在前端
 * 判断 —— 前端没有交易日历，而在节假日多轮询几次只是几个立即返回的空转请求，
 * 代价远小于维护一份会过期的本地假期表。真正的交易日判定在后端。
 *
 * **时刻一律按北京时间（Asia/Shanghai）折算，不看浏览器本地时区**。后端用
 * `Asia/Shanghai` 判断交易日与收盘，前端若按本地时区判断，非 UTC+8 的浏览器会
 * 把整个轮询窗口平移（UTC 机器的 01:30 是北京 09:30，本地时区会判成非交易时段，
 * 于是开盘后不再刷新）。这里用 `Intl.DateTimeFormat` 做换算，不依赖运行环境。
 */
const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'

const MORNING_OPEN_MINUTES = 9 * 60 + 30
const MORNING_CLOSE_MINUTES = 11 * 60 + 30
const AFTERNOON_OPEN_MINUTES = 13 * 60
const AFTERNOON_CLOSE_MINUTES = 15 * 60

const WEEKEND = new Set(['Sat', 'Sun'])

/*
 * `hourCycle: 'h23'` 而不是 `hour12: false`：后者在部分实现里会把午夜给成 "24"，
 * 于是 `24 * 60 = 1440` 分，任何时段都比不上，等于整个 00:00 这一分钟失效。
 */
const SHANGHAI_CLOCK = new Intl.DateTimeFormat('en-US', {
  timeZone: SHANGHAI_TIME_ZONE,
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

function shanghaiClock(now) {
  const parts = Object.fromEntries(
    SHANGHAI_CLOCK.formatToParts(now).map((part) => [part.type, part.value]),
  )
  return {
    weekday: parts.weekday,
    minutes: Number(parts.hour) * 60 + Number(parts.minute),
  }
}

export function isTradingSession(now = new Date()) {
  const { weekday, minutes } = shanghaiClock(now)
  if (WEEKEND.has(weekday)) {
    return false
  }
  const inMorning = minutes >= MORNING_OPEN_MINUTES && minutes <= MORNING_CLOSE_MINUTES
  const inAfternoon = minutes >= AFTERNOON_OPEN_MINUTES && minutes <= AFTERNOON_CLOSE_MINUTES
  return inMorning || inAfternoon
}
