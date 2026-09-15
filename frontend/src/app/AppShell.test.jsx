import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import App from '../App'


function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function sessionResponse(authenticated) {
  return {
    status: 'success',
    data: {
      authenticated,
      user: authenticated ? { id: 1, username: 'lian', is_staff: false } : null,
      csrf_token: 'csrf-token',
    },
  }
}

const allModules = [
  { id: 'kaipanla', display_name: '开盘啦', navigation_group: 'fund_flow', navigation_order: 10 },
  { id: 'stock_moves', display_name: '大涨跌幅与大成交量个股', navigation_group: 'analysis', navigation_order: 20 },
  { id: 'sector_momentum', display_name: '板块动量', navigation_group: 'analysis', navigation_order: 30 },
  { id: 'hundred_day', display_name: '百日新高新低占比', navigation_group: 'analysis', navigation_order: 40 },
]

function modulesResponse(modules) {
  return { status: 'success', data: modules }
}


describe('App shell', () => {
  it('shows only the login page for an anonymous session and never requests business data', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(sessionResponse(false)))

    render(<App fetchImpl={fetchImpl} />)

    expect(await screen.findByRole('heading', { name: '登录' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '板块资金流' })).not.toBeInTheDocument()
    expect(fetchImpl.mock.calls.map(([path]) => path)).toEqual(['/api/core/session/'])
  })

  it('logs in and defaults to the Kaipanla fund-flow tab with all approved labels', async () => {
    let authenticated = false
    const fetchImpl = vi.fn(async (path) => {
      if (path === '/api/core/session/') {
        return jsonResponse(sessionResponse(authenticated))
      }
      if (path === '/api/core/login/') {
        authenticated = true
        return jsonResponse(sessionResponse(true))
      }
      if (path === '/api/core/modules/') {
        return jsonResponse(modulesResponse(allModules))
      }
      if (path === '/api/kaipanla/sectors/intraday/?inflow_top=25&outflow_top=25') {
        return jsonResponse({
          status: 'success',
          business_date: '2026-09-09',
          data: { time_points: [], series: [] },
        })
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<App fetchImpl={fetchImpl} />)

    await screen.findByRole('heading', { name: '登录' })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'lian' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('暂无数据')).toBeInTheDocument()
    // 空数据只隐藏图表与榜单，日期与统计窗口控件保留在页面上。
    expect(screen.getByLabelText('数据日期')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '当日' })).toBeInTheDocument()
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/kaipanla/sectors/intraday/?inflow_top=25&outflow_top=25',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
    expect(screen.getByRole('tabpanel', { name: '开盘啦' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '板块资金流' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '大涨跌幅与大成交量个股' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '板块动量' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '百日新高新低占比' })).toBeInTheDocument()
    // 四个一级 Tab 只保留文字标签：左侧图标已按需求去掉，标签里不再有 svg。
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(4)
    expect(tabs.map((tab) => tab.querySelector('svg'))).toEqual([null, null, null, null])
  })

  it('never renders the removed data-source switcher or the module breadcrumb', async () => {
    const fetchImpl = vi.fn(async (path) => {
      if (path === '/api/core/session/') return jsonResponse(sessionResponse(true))
      if (path === '/api/core/modules/') return jsonResponse(modulesResponse(allModules))
      if (path === '/api/kaipanla/sectors/intraday/?inflow_top=25&outflow_top=25') {
        return jsonResponse({
          status: 'success',
          business_date: '2026-09-09',
          data: { time_points: [], series: [] },
        })
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<App fetchImpl={fetchImpl} />)

    expect(await screen.findByRole('tabpanel', { name: '开盘啦' })).toBeInTheDocument()
    expect(screen.queryByText('数据源')).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '板块资金流子模块' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '开盘啦' })).not.toBeInTheDocument()
    expect(screen.queryByText(/^当前模块：/)).not.toBeInTheDocument()
  })

  it('uses the first enabled module when Kaipanla is disabled', async () => {
    const modules = allModules.filter((module) => module.id !== 'kaipanla')
    const fetchImpl = vi.fn(async (path) => {
      if (path === '/api/core/session/') return jsonResponse(sessionResponse(true))
      if (path === '/api/core/modules/') return jsonResponse(modulesResponse(modules))
      if (path === '/api/stock-moves/') {
        return jsonResponse({
          status: 'error', error: { code: 'DATA_PREPARING' }, data: null,
        }, 202)
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<App fetchImpl={fetchImpl} />)

    expect(await screen.findByRole('tabpanel', { name: '大涨跌幅与大成交量个股' })).toBeInTheDocument()
    expect(await screen.findByText('数据准备中，请稍后刷新。')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '板块资金流' })).not.toBeInTheDocument()
  })

  it('shows an explicit empty state when no business modules are enabled', async () => {
    const fetchImpl = vi.fn(async (path) => {
      if (path === '/api/core/session/') return jsonResponse(sessionResponse(true))
      if (path === '/api/core/modules/') return jsonResponse(modulesResponse([]))
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<App fetchImpl={fetchImpl} />)

    expect(await screen.findByText('暂无已启用模块')).toBeInTheDocument()
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
  })

  it('returns to the login page after the modules request reports an expired session', async () => {
    let sessionReads = 0
    const fetchImpl = vi.fn(async (path) => {
      if (path === '/api/core/session/') {
        sessionReads += 1
        return jsonResponse(sessionResponse(sessionReads === 1))
      }
      if (path === '/api/core/modules/') {
        return jsonResponse({
          status: 'error', error: { code: 'AUTH_REQUIRED', message: '请先登录。' },
        }, 401)
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<App fetchImpl={fetchImpl} />)

    expect(await screen.findByRole('heading', { name: '登录' })).toBeInTheDocument()
    await waitFor(() => expect(sessionReads).toBeGreaterThanOrEqual(2))
  })

  it('shows a generic message when login credentials are rejected', async () => {
    const fetchImpl = vi.fn(async (path) => {
      if (path === '/api/core/session/') return jsonResponse(sessionResponse(false))
      if (path === '/api/core/login/') {
        return jsonResponse({
          status: 'error', error: { code: 'AUTH_REQUIRED', message: '用户名或密码错误。' },
        }, 401)
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<App fetchImpl={fetchImpl} />)

    await screen.findByRole('heading', { name: '登录' })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'lian' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('登录失败，请检查用户名和密码。')
  })

  it('supports keyboard navigation between primary tabs without removing the navigation', async () => {
    const fetchImpl = vi.fn(async (path) => {
      if (path === '/api/core/session/') return jsonResponse(sessionResponse(true))
      if (path === '/api/core/modules/') return jsonResponse(modulesResponse(allModules))
      if (path === '/api/kaipanla/sectors/intraday/?inflow_top=25&outflow_top=25') {
        return jsonResponse({ status: 'success', data: { time_points: [], series: [] } })
      }
      if (path === '/api/stock-moves/') {
        return jsonResponse({ status: 'error', error: { code: 'DATA_PREPARING' }, data: null }, 202)
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    render(<App fetchImpl={fetchImpl} />)

    const fundFlowTab = await screen.findByRole('tab', { name: '板块资金流' })
    fundFlowTab.focus()
    fireEvent.keyDown(fundFlowTab, { key: 'ArrowRight' })

    expect(await screen.findByRole('tabpanel', { name: '大涨跌幅与大成交量个股' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '板块资金流' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '百日新高新低占比' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '大涨跌幅与大成交量个股' })).toHaveAttribute('aria-selected', 'true')
  })
})
