/**
 * @vitest-environment node
 *
 * 这条用例做的事只有"读文件 + 算色相"，全程不碰 DOM，所以显式要 node 环境。
 * jsdom 下 `import.meta.url` 不是 file URL，`new URL('./tokens.css', import.meta.url)`
 * 会抛 `TypeError: The URL must be of scheme file` —— 这不是被测代码的问题，
 * 是环境选错了。改用 CWD 相对路径能绕过，但会把用例绑死在调用目录上，更糟。
 */
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

/*
 * 设计令牌里的产品约定，按**语义**断而不是按字面值断。
 *
 * 这里只放一条：A 股习惯是**涨红跌绿**（与欧美相反）。把两个令牌写反不会让任何
 * 组件报错、不会让任何布局错位，只会让全站的红绿含义整体反向 —— 这是最容易发生
 * 也最难被其它用例发现的回归，所以值得一条用例专门盯住色相。
 *
 * 不要退化成"断言某个十六进制值"：那只是把令牌抄一遍，改配色就得改用例，而写反
 * 了却照样通过（只要两边一起改）。
 */
function hue(hex) {
  const [red, green, blue] = [1, 3, 5]
    .map((index) => parseInt(hex.slice(index, index + 2), 16) / 255)
  const max = Math.max(red, green, blue)
  const min = Math.min(red, green, blue)
  const span = max - min
  if (span === 0) {
    return 0
  }
  const sector = max === red
    ? ((green - blue) / span) % 6
    : max === green
      ? (blue - red) / span + 2
      : (red - green) / span + 4
  return (sector * 60 + 360) % 360
}

/* 用 `import.meta.url` 定位，不依赖进程的工作目录。 */
const TOKENS = readFileSync(new URL('./tokens.css', import.meta.url), 'utf8')

function token(name) {
  const match = TOKENS.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`))
  if (!match) {
    throw new Error(`Token ${name} is not a plain hex value in tokens.css.`)
  }
  return match[1]
}

describe('market color tokens', () => {
  it('keeps the A-share convention: up is red, down is green', () => {
    const up = token('--color-market-up')
    const down = token('--color-market-down')

    // 红在色环两端（≈0°/360°），绿在中间偏青（≈120°）。写反 → 这里立刻红。
    expect(hue(up) >= 330 || hue(up) <= 20).toBe(true)
    expect(hue(down)).toBeGreaterThan(90)
    expect(hue(down)).toBeLessThan(170)

    expect(up).not.toBe(down)
  })

  it('keeps the error color distinct from the up color', () => {
    // 错误色也是红的，和"涨"挨得很近：正是这种接近让人敢把它们复用成同一个值。
    // 一旦复用，涨跌色就再也不能单独调整，运维看到的"红"也分不清是涨还是故障。
    expect(token('--color-error')).not.toBe(token('--color-market-up'))
    expect(token('--color-error')).not.toBe(token('--color-market-down'))
  })
})
