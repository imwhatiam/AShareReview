import { fireEvent, screen } from '@testing-library/react'

const MONTH_TITLE = /^(\d{4})年(\d{1,2})月$/

/*
 * 在测试中点选日期。
 *
 * 弹层默认停在 value 所在月（value 为空时是“今天”所在月），因此这里先按月份导航到
 * 目标月再点日，避免测试结果随运行日期漂移（例如跨月后 9 月 8 日不在首屏网格里）。
 */
export function pickDate(target) {
  const [year, month] = target.split('-').map(Number)
  fireEvent.click(screen.getByLabelText('数据日期'))

  for (let guard = 0; guard < 120; guard += 1) {
    const match = MONTH_TITLE.exec(screen.getByText(MONTH_TITLE).textContent)
    const delta = (year - Number(match[1])) * 12 + (month - Number(match[2]))
    if (delta === 0) {
      break
    }
    fireEvent.click(screen.getByRole('button', { name: delta > 0 ? '下一个月' : '上一个月' }))
  }

  fireEvent.click(screen.getByRole('button', { name: target }))
}
