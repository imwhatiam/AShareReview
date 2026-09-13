import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import DatePicker from './DatePicker'

function setup(value = '2026-09-09') {
  const onChange = vi.fn()
  render(<DatePicker id="test-date" value={value} onChange={onChange} />)
  return onChange
}

describe('DatePicker', () => {
  it('shows the selected date, and the latest-trading-day placeholder when empty', () => {
    const { unmount } = render(<DatePicker id="a" value="2026-09-09" onChange={() => {}} />)
    expect(screen.getByLabelText('数据日期')).toHaveTextContent('2026-09-09')
    unmount()

    render(<DatePicker id="b" value="" onChange={() => {}} />)
    expect(screen.getByLabelText('数据日期')).toHaveTextContent('最新交易日')
    expect(screen.getByLabelText('数据日期')).toHaveAttribute('aria-expanded', 'false')
  })

  it('opens a self-drawn calendar on the selected month instead of the native picker', () => {
    setup()
    fireEvent.click(screen.getByLabelText('数据日期'))

    expect(screen.getByRole('dialog', { name: '数据日期日历' })).toBeInTheDocument()
    expect(screen.getByLabelText('数据日期')).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('2026年9月')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '2026-09-09' })).toHaveAttribute('aria-current', 'date')
  })

  it('emits an ISO date and closes the popover once a day is chosen', () => {
    const onChange = setup()
    fireEvent.click(screen.getByLabelText('数据日期'))
    fireEvent.click(screen.getByRole('button', { name: '2026-09-08' }))

    expect(onChange).toHaveBeenCalledWith('2026-09-08')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByLabelText('数据日期')).toHaveFocus()
  })

  it('moves roving focus with arrow keys, crossing month boundaries', () => {
    setup('2026-09-01')
    fireEvent.click(screen.getByLabelText('数据日期'))

    const first = screen.getByRole('button', { name: '2026-09-01' })
    expect(first).toHaveFocus()

    fireEvent.keyDown(first, { key: 'ArrowLeft' })
    expect(screen.getByText('2026年8月')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '2026-08-31' })).toHaveFocus()
  })

  it('navigates months and years from the header', () => {
    setup()
    fireEvent.click(screen.getByLabelText('数据日期'))

    fireEvent.click(screen.getByRole('button', { name: '下一年' }))
    expect(screen.getByText('2027年9月')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '上一个月' }))
    expect(screen.getByText('2027年8月')).toBeInTheDocument()
  })

  it('closes on Escape or an outside pointer press, returning focus to the trigger', () => {
    setup()
    const trigger = screen.getByLabelText('数据日期')

    fireEvent.click(trigger)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()

    fireEvent.click(trigger)
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keeps Tab inside the calendar dialog', () => {
    setup('2026-09-01')
    fireEvent.click(screen.getByLabelText('数据日期'))

    expect(screen.getByRole('dialog', { name: '数据日期日历' })).toHaveAttribute('aria-modal', 'true')

    /* 漫游 tabindex 的日格子不算可 Tab 项：最后一个可 Tab 项是页脚的「最新交易日」。 */
    const lastAction = screen.getByRole('button', { name: '最新交易日' })
    lastAction.focus()
    fireEvent.keyDown(lastAction, { key: 'Tab' })

    const firstAction = screen.getByRole('button', { name: '上一年' })
    expect(firstAction).toHaveFocus()

    fireEvent.keyDown(firstAction, { key: 'Tab', shiftKey: true })
    expect(screen.getByRole('button', { name: '最新交易日' })).toHaveFocus()
  })

  it('clears the selection back to the latest trading day from the footer', () => {
    const onChange = setup()
    fireEvent.click(screen.getByLabelText('数据日期'))
    fireEvent.click(screen.getByRole('button', { name: '最新交易日' }))

    expect(onChange).toHaveBeenCalledWith('')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
