/*
 * 四个页面的测试共用的响应信封工厂。
 *
 * `DATA_UPDATED_AT` 是信封里的数据时刻：卡片工具栏那颗「更新于」显示的是**库里这份
 * 数据是什么时候写的**（资金流页是"最新采集槽那批行的写入时刻"），而不是这次请求的
 * 时刻。用本地时刻转 ISO，断言与测试机器的时区无关。
 */
export const DATA_UPDATED_AT = new Date(2026, 8, 9, 15, 35).toISOString()

/* `overrides` 用来换业务日期、`data_updated_at`，或者故意把 `status` 压成 partial。 */
export function envelope(data, overrides = {}) {
  return {
    status: 'ok',
    business_date: '2026-09-09',
    stale: false,
    warnings: [],
    data,
    ...overrides,
  }
}
