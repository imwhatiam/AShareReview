import { describe, expect, it } from 'vitest'

import { ANIMATION_DURATION_MS } from '../../shared/charts/chartBaseline'
import { flowOption } from './flowOption'

/*
 * 资金流的 option 构造器搬出 `shared/charts/` 后，它和另外两张盘后图的
 * "同一套入场动画"仍要有人守（那两张在 `shared/charts/chartTheme.test.js`）。
 * 断的是"取自 `chartBaseline.ANIMATION_DURATION_MS`"，不是抄一遍 320 ——
 * 时长可以调，漂移才是 bug。
 *
 * 图本身的形状（刻度、线端标签、右端留白）由 `flowView.test.jsx` 走真实组件
 * 断言，这里不重复。
 */
describe('flowOption', () => {
  it('takes the entrance animation from the shared baseline', () => {
    const option = flowOption({ timePoints: ['09:30'], series: [] })

    expect(option.animationDuration).toBe(ANIMATION_DURATION_MS)
  })
})
