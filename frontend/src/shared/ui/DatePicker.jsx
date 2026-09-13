import { useCallback, useEffect, useRef, useState } from 'react'

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']
const POPOVER_WIDTH = 272
const POPOVER_GAP = 8
/* 只用于判断弹层该朝上还是朝下展开的估算高度。 */
const POPOVER_ESTIMATED_HEIGHT = 336

/*
 * 弹层里能 Tab 到的元素。日按钮用漫游 tabindex（同一个月里只有一天是 0，其余是
 * -1），所以取到之后还要按 `tabIndex` 过滤：只按选择器取，整月三十来个格子都会
 * 算进来，焦点陷阱里的"最后一个"就永远落在某一天上，周日按钮之后的"今天/最新
 * 交易日"两个按钮会被跳过。
 */
const FOCUSABLE_SELECTOR = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])'

function focusableIn(container) {
  return Array.from(container?.querySelectorAll(FOCUSABLE_SELECTOR) ?? [])
    .filter((element) => element.tabIndex !== -1)
}

function pad(value) {
  return String(value).padStart(2, '0')
}

function toIso(year, month, day) {
  return `${year}-${pad(month + 1)}-${pad(day)}`
}

function parseIso(text) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text ?? '')
  if (!match) {
    return null
  }
  const year = Number(match[1])
  const month = Number(match[2]) - 1
  const day = Number(match[3])
  const probe = new Date(year, month, day)
  if (probe.getFullYear() !== year || probe.getMonth() !== month || probe.getDate() !== day) {
    return null
  }
  return { year, month, day }
}

function todayParts() {
  const now = new Date()
  return { year: now.getFullYear(), month: now.getMonth(), day: now.getDate() }
}

function daysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate()
}

/* 生成按周对齐的月历格子，首尾用 null 补齐整周。 */
function buildCells(year, month) {
  const lead = new Date(year, month, 1).getDay()
  const total = daysInMonth(year, month)
  const cells = Array.from({ length: lead }, () => null)
  for (let day = 1; day <= total; day += 1) {
    cells.push(day)
  }
  while (cells.length % 7 !== 0) {
    cells.push(null)
  }
  return cells
}

/*
 * 自绘日期选择器。
 *
 * 原生 `input[type=date]` 的日历弹层位于浏览器 UA shadow DOM，页面样式无法覆盖，
 * 视觉上会与产品整体风格割裂，因此改为自绘触发器 + 弹层。
 * 触发器沿用 `.field__input` 的边框 / 圆角 / 字号尺度，可访问名仍挂在触发器上，
 * 与页面其他字段保持一致（label 默认“数据日期”）。
 */
export default function DatePicker({
  id,
  label = '数据日期',
  placeholder = '最新交易日',
  value,
  onChange,
}) {
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState(todayParts)
  const [focusDay, setFocusDay] = useState(null)
  const [placement, setPlacement] = useState(null)
  const triggerRef = useRef(null)
  const popoverRef = useRef(null)
  const pendingFocus = useRef(false)

  const selected = parseIso(value)
  const today = todayParts()

  const measure = useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) {
      return
    }
    const rect = trigger.getBoundingClientRect()
    const left = Math.max(
      POPOVER_GAP,
      Math.min(rect.left, window.innerWidth - POPOVER_WIDTH - POPOVER_GAP),
    )
    const flip = (
      rect.bottom + POPOVER_GAP + POPOVER_ESTIMATED_HEIGHT > window.innerHeight
      && rect.top > POPOVER_ESTIMATED_HEIGHT
    )
    setPlacement({
      left,
      width: POPOVER_WIDTH,
      /* 朝上展开时贴住触发器上沿，弹层高度变化不会造成错位。 */
      ...(flip
        ? { bottom: window.innerHeight - rect.top + POPOVER_GAP }
        : { top: rect.bottom + POPOVER_GAP }),
    })
  }, [])

  const closePopover = useCallback(({ restoreFocus = false } = {}) => {
    setOpen(false)
    if (restoreFocus) {
      triggerRef.current?.focus()
    }
  }, [])

  function openPopover() {
    const base = selected ?? today
    setCursor({ year: base.year, month: base.month })
    pendingFocus.current = true
    setFocusDay(base.day)
    measure()
    setOpen(true)
  }

  function togglePopover() {
    if (open) {
      closePopover()
    } else {
      openPopover()
    }
  }

  function commit(year, month, day) {
    onChange(toIso(year, month, day))
    closePopover({ restoreFocus: true })
  }

  function shift({ months = 0, years = 0 }) {
    const next = new Date(cursor.year, cursor.month + months + years * 12, 1)
    const year = next.getFullYear()
    const month = next.getMonth()
    setCursor({ year, month })
    setFocusDay((current) => (
      current === null ? null : Math.min(current, daysInMonth(year, month))
    ))
  }

  function onGridKeyDown(event) {
    const offsets = {
      ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7,
    }
    if (!(event.key in offsets)) {
      return
    }
    event.preventDefault()
    const target = new Date(cursor.year, cursor.month, (focusDay ?? 1) + offsets[event.key])
    setCursor({ year: target.getFullYear(), month: target.getMonth() })
    pendingFocus.current = true
    setFocusDay(target.getDate())
  }

  useEffect(() => {
    if (!open) {
      return undefined
    }
    measure()

    function onPointerDown(event) {
      if (popoverRef.current?.contains(event.target)) {
        return
      }
      if (triggerRef.current?.contains(event.target)) {
        return
      }
      closePopover()
    }

    function onKeyDown(event) {
      if (event.key === 'Escape') {
        closePopover({ restoreFocus: true })
      }
    }

    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, measure, closePopover])

  useEffect(() => {
    if (!open || !pendingFocus.current || focusDay === null) {
      return
    }
    pendingFocus.current = false
    popoverRef.current?.querySelector(`[data-day="${focusDay}"]`)?.focus()
  }, [open, focusDay, cursor])

  /*
   * 日历弹层声明为 `role="dialog"` + `aria-modal="true"`（WAI-ARIA 的日期选择器
   * 对话框模式），因此 Tab 必须在弹层内部循环。不循环的话，读屏已经被告知这是个
   * 模态对话框，键盘却会走到弹层**后面**的页面控件上。Escape 与点击外部仍可关闭
   * 并把焦点还给触发器（见下面的全局监听），所以陷阱不会把键盘用户困住。
   */
  function onPopoverKeyDown(event) {
    if (event.key !== 'Tab') {
      return
    }
    const focusables = focusableIn(popoverRef.current)
    if (focusables.length === 0) {
      return
    }
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    const active = document.activeElement
    const inside = Boolean(popoverRef.current?.contains(active))
    if (event.shiftKey) {
      if (!inside || active === first) {
        event.preventDefault()
        last.focus()
      }
    } else if (!inside || active === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const cells = buildCells(cursor.year, cursor.month)
  const isToday = (day) => (
    cursor.year === today.year && cursor.month === today.month && day === today.day
  )
  const isSelected = (day) => (
    selected !== null
    && selected.year === cursor.year
    && selected.month === cursor.month
    && selected.day === day
  )

  return (
    <div className="date-picker">
      <button
        ref={triggerRef}
        id={id}
        type="button"
        className={`date-picker__trigger${selected === null ? ' is-placeholder' : ''}`}
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={togglePopover}
      >
        <span className="date-picker__value">{selected ? toIso(selected.year, selected.month, selected.day) : placeholder}</span>
        <svg className="date-picker__icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <rect x="2.4" y="3.4" width="11.2" height="10.2" rx="1.8" />
          <path d="M2.4 6.8h11.2" />
          <path d="M5.6 1.9v2.6M10.4 1.9v2.6" />
        </svg>
      </button>

      {open && placement !== null && (
        <div
          ref={popoverRef}
          className="date-picker__popover"
          role="dialog"
          aria-modal="true"
          aria-label={`${label}日历`}
          onKeyDown={onPopoverKeyDown}
          style={placement}
        >
          <div className="date-picker__head">
            <button type="button" className="date-picker__nav" aria-label="上一年" onClick={() => shift({ years: -1 })}>«</button>
            <button type="button" className="date-picker__nav" aria-label="上一个月" onClick={() => shift({ months: -1 })}>‹</button>
            <span className="date-picker__title" aria-live="polite">{cursor.year}年{cursor.month + 1}月</span>
            <button type="button" className="date-picker__nav" aria-label="下一个月" onClick={() => shift({ months: 1 })}>›</button>
            <button type="button" className="date-picker__nav" aria-label="下一年" onClick={() => shift({ years: 1 })}>»</button>
          </div>

          <div className="date-picker__weekdays" aria-hidden="true">
            {WEEKDAYS.map((weekday) => (
              <span key={weekday} className="date-picker__weekday">{weekday}</span>
            ))}
          </div>

          <div className="date-picker__grid" onKeyDown={onGridKeyDown}>
            {cells.map((day, index) => (day === null ? (
              <span key={`blank-${index}`} className="date-picker__blank" aria-hidden="true" />
            ) : (
              <button
                key={day}
                type="button"
                data-day={day}
                className={`date-picker__day${isToday(day) ? ' is-today' : ''}`}
                aria-label={toIso(cursor.year, cursor.month, day)}
                aria-current={isSelected(day) ? 'date' : undefined}
                tabIndex={day === focusDay ? 0 : -1}
                onClick={() => commit(cursor.year, cursor.month, day)}
              >
                {day}
              </button>
            )))}
          </div>

          <div className="date-picker__foot">
            <button
              type="button"
              className="date-picker__action"
              onClick={() => commit(today.year, today.month, today.day)}
            >
              今天
            </button>
            <button
              type="button"
              className="date-picker__action"
              onClick={() => {
                onChange('')
                closePopover({ restoreFocus: true })
              }}
            >
              最新交易日
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
