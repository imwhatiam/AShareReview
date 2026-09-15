import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, vi } from 'vitest'

import { DATA_UPDATED_AT, envelope } from './envelope'

/*
 * 2026-09-14：自动轮询删除后，「更新于 HH:MM」是刷新当前页面数据的唯一入口。
 * 断言"又发了同一个请求"，而不是"页面上多了点什么" —— 这个入口失效的表现正是
 * 点了没反应，只有请求次数能发现它。四个页面守的是同一条不变量，所以只留一份实现。
 *
 * `endpoint` 由调用方给：三个按日期取数的页面写字面量，资金流页有查询串，用它的
 * 路径构造函数给出。**不在这里替调用方推导** —— 拿生产代码算期望值时，构造函数
 * 自己写错也照样全绿。
 */
export async function expectRefreshRefetches(Page, { payload, endpoint }) {
  const apiClient = {
    request: vi.fn().mockResolvedValue(envelope(payload, { data_updated_at: DATA_UPDATED_AT })),
  }
  render(<Page apiClient={apiClient} />)

  // 按钮上的时刻必须是信封给的数据时刻：本轮之前它显示的是 Date.now()。
  fireEvent.click(await screen.findByRole('button', { name: /更新于 15:35/ }))

  await waitFor(() => expect(apiClient.request).toHaveBeenCalledTimes(2))
  expect(apiClient.request.mock.calls[0][0]).toBe(endpoint)
  expect(apiClient.request.mock.calls[1][0]).toBe(endpoint)
}
