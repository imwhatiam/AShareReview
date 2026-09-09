import { readFileSync } from 'node:fs'

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import DataState from './DataState'


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

  it('keeps stale, partial, warning, business-date, and version information visible with content', () => {
    render(
      <DataState
        businessDate="2026-09-09"
        dataVersion="kaipanla:20260909-1"
        stale
        partial
        warnings={['东方财富上游暂不可用，正在展示最近可用数据。']}
      >
        <p>业务页面正文</p>
      </DataState>,
    )

    expect(screen.getByText('业务页面正文')).toBeInTheDocument()
    expect(screen.getByText('业务日期：2026-09-09')).toBeInTheDocument()
    expect(screen.getByText('数据版本：kaipanla:20260909-1')).toBeInTheDocument()
    expect(screen.getByText('正在展示旧数据')).toBeInTheDocument()
    expect(screen.getByText('部分数据')).toBeInTheDocument()
    expect(screen.getByText('东方财富上游暂不可用，正在展示最近可用数据。')).toBeInTheDocument()
  })

  it('defines separate market-up, market-down, and error color tokens', () => {
    const tokens = readFileSync('src/styles/tokens.css', 'utf8')
    const up = tokens.match(/--color-market-up:\s*([^;]+);/)[1]
    const down = tokens.match(/--color-market-down:\s*([^;]+);/)[1]
    const error = tokens.match(/--color-error:\s*([^;]+);/)[1]

    expect(up).not.toBe(down)
    expect(error).not.toBe(up)
    expect(error).not.toBe(down)
  })
})

  it('defines visible keyboard focus and narrow-screen tab layout rules', () => {
    const styles = readFileSync('src/index.css', 'utf8')

    expect(styles).toContain(':focus-visible')
    expect(styles).toContain('@media (max-width: 40rem)')
    expect(styles).toContain('overflow-x: auto')
  })
