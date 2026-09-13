import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import DataState from './DataState'

/*
 * 这里曾经有两条"读 CSS 文件、断言子串"的用例（tokens.css 的三个颜色两两不等、
 * index.css 里有 `:focus-visible` / `@media (max-width: 40rem)` / `overflow-x`）。
 * 它们测的是文件文本而不是行为，换个写法就碎，而真正的回归（涨跌色写反、焦点环
 * 丢了）一个都拦不住。现在：
 *
 * - "涨是红、跌是绿"这条产品约定移到了 `src/styles/tokens.test.js`，按色相断，
 *   写反了就会红；
 * - 焦点可见性与窄屏布局由 `frontend-visual-verification` 流程（真实渲染 + 截图）
 *   负责 —— jsdom 不做层叠与命中测试，在这里断言字符串只是自我安慰。
 */

describe('DataState', () => {
  it.each([
    ['loading', '正在加载数据…'],
    ['empty', '暂无数据'],
    ['preparing', '数据准备中，请稍后刷新。'],
  ])('renders the %s state as accessible status text', (state, message) => {
    render(<DataState state={state} />)

    expect(screen.getByRole('status')).toHaveTextContent(message)
  })

  it('renders failure as an alert instead of a market direction indicator', () => {
    render(<DataState state="error" message="数据暂时无法加载。" />)

    expect(screen.getByRole('alert')).toHaveTextContent('数据暂时无法加载。')
    expect(screen.getByRole('alert')).toHaveClass('data-state--error')
  })

  it('keeps stale and warning information visible with content', () => {
    render(
      <DataState
        stale
        warnings={['数据源上游暂不可用，正在展示最近可用数据。']}
      >
        <p>业务页面正文</p>
      </DataState>,
    )

    expect(screen.getByText('业务页面正文')).toBeInTheDocument()
    expect(screen.getByText('正在展示旧数据')).toBeInTheDocument()
    expect(screen.getByText('数据源上游暂不可用，正在展示最近可用数据。')).toBeInTheDocument()
  })

  it('never renders the removed partial-data chip, which duplicated the warning list', () => {
    render(
      <DataState
        status="partial"
        partial
        warnings={['数据源上游暂不可用，正在展示最近可用数据。']}
      >
        <p>业务页面正文</p>
      </DataState>,
    )

    expect(screen.queryByText('部分数据')).not.toBeInTheDocument()
  })

  it('never renders the removed business-date and data-version chips', () => {
    render(
      <DataState
        state="empty"
        businessDate="2026-09-09"
        dataVersion="kaipanla:20260909-1"
      />,
    )

    expect(screen.getByText('暂无数据')).toBeInTheDocument()
    expect(screen.queryByText(/^业务日期：/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^数据版本：/)).not.toBeInTheDocument()
  })
})
