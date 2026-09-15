import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import RefreshStamp from './RefreshStamp'

/*
 * 「更新于 HH:MM」的落点变了（DataMeta → 工具栏日期控件右侧），断言跟着搬家；
 * 2026-09-14 它又多了一重身份：**刷新当前页面数据的唯一入口**（自动轮询已删除）。
 * 所以这里除了"有时刻就显示、没时刻就不渲染"，还要钉住它是一颗能点的按钮。
 *
 * 时刻的含义也在 2026-09-14 变了：从"这份数据是几点取回来的"改成"库里这份数据是
 * 几点写的"，输入随之从数字时间戳变成服务端发来的 ISO 串。下面用本地时刻再转 ISO，
 * 这样断言与测试机器的时区无关（`new Date(本地时刻).toISOString()` 往返回同一个钟点）。
 */
const DATA_UPDATED_AT = new Date(2026, 8, 11, 14, 35).toISOString()

describe('RefreshStamp', () => {
  it('shows when the stored data was written so a refresh is visible', () => {
    render(<RefreshStamp updatedAt={DATA_UPDATED_AT} />)

    expect(screen.getByText(/更新于 14:35/)).toBeInTheDocument()
  })

  it('is a button that asks for fresh data when clicked', () => {
    const onRefresh = vi.fn()
    render(<RefreshStamp updatedAt={DATA_UPDATED_AT} onRefresh={onRefresh} />)

    // 必须能被读成按钮：刷新入口的可达性就靠它（原来是 <span>，键盘与读屏都够不到）。
    const stamp = screen.getByRole('button', { name: /更新于 14:35/ })
    fireEvent.click(stamp)

    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it('renders nothing without a timestamp', () => {
    // 首次加载中、请求失败、以及"这一天没有数据"的空态都属于这一类：没有数据就没有
    // "数据是什么时候写的"，不能拿当前时间冒充。
    const { container } = render(<RefreshStamp />)

    expect(screen.queryByText(/更新于/)).not.toBeInTheDocument()
    expect(container).toBeEmptyDOMElement()
  })
})
