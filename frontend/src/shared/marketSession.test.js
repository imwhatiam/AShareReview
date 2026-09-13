import { describe, expect, it } from 'vitest'

import { isTradingSession } from './marketSession'

/*
 * 2026-09-11 是周五，09-12 / 09-13 是周末。
 *
 * 全部用**带时区的 ISO 串**构造瞬间，而不是 `new Date(2026, 8, 11, 9, 30)`：
 * 前者让结论只取决于北京时间，跑在 UTC 或美西的机器上结果一样；后者按本地时区
 * 解释，测试会随运行机器的时区变绿变红，反而掩盖了这里唯一要保住的性质。
 */
function beijing(day, time) {
  return new Date(`2026-09-${day}T${time}:00+08:00`)
}

describe('isTradingSession', () => {
  it.each([
    ['before the open', beijing(11, '09:29'), false],
    ['morning open', beijing(11, '09:30'), true],
    ['morning close', beijing(11, '11:30'), true],
    ['the midday break', beijing(11, '12:00'), false],
    ['afternoon open', beijing(11, '13:00'), true],
    ['the closing bell', beijing(11, '15:00'), true],
    ['after the close', beijing(11, '15:01'), false],
  ])('is %s', (_name, now, expected) => {
    expect(isTradingSession(now)).toBe(expected)
  })

  it('is closed all weekend', () => {
    expect(isTradingSession(beijing(12, '10:00'))).toBe(false)
    expect(isTradingSession(beijing(13, '10:00'))).toBe(false)
  })

  /*
   * 判定必须锚定北京时间，而不是浏览器本地时区。这两个瞬间在一台 UTC 机器上
   * 分别是 01:30 与 13:00：按本地时区会判成"开盘前"与"交易中"，按北京时间却是
   * 09:30（开盘）与 21:00（已收盘）。两个方向都要挡住，否则非 UTC+8 的浏览器
   * 会把整个轮询窗口整体平移。
   */
  it('reads the Beijing clock wherever the browser runs', () => {
    expect(isTradingSession(new Date('2026-09-11T01:30:00Z'))).toBe(true)
    expect(isTradingSession(new Date('2026-09-11T13:00:00Z'))).toBe(false)
  })
})
