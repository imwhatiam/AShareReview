import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import RefreshStamp from './RefreshStamp'

/*
 * 「更新于 HH:MM」的落点变了（DataMeta → 工具栏日期控件右侧），断言跟着搬家，
 * 覆盖的内容不变：有时间就显示、没时间就不渲染。页面级的落点由各页面测试的
 * 工具栏断言兜底。
 */
describe('RefreshStamp', () => {
  it('shows when the data was fetched so an intraday refresh is visible', () => {
    render(<RefreshStamp refreshedAt={new Date(2026, 8, 11, 14, 35).getTime()} />)

    expect(screen.getByText(/更新于 14:35/)).toBeInTheDocument()
  })

  it('renders nothing while a request is still in flight', () => {
    const { container } = render(<RefreshStamp />)

    expect(screen.queryByText(/更新于/)).not.toBeInTheDocument()
    expect(container).toBeEmptyDOMElement()
  })
})
