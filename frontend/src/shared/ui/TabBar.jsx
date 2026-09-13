import { useRef } from 'react'

const STEP_KEYS = { ArrowRight: 1, ArrowLeft: -1 }

/*
 * 统一的选项卡条：漫游 tabindex + 左右/Home/End 键盘移动。
 *
 * 当前只有一级导航在用（底部指示条，`.tabs--primary`）。2026-09-13 删掉了
 * `variant` 参数：唯一的调用方恒传 `primary`，而曾经存在的 `tabs--segmented`
 * 胶囊样式已随二级导航一并删除 —— 这个旋钮传别的值只会得到没有样式的裸 tablist，
 * 是一个**已知无效的可配置项**。将来真要加二级导航，再按需引入变体。
 *
 * 可访问名只挂在一处：外层 `<nav>` 是地标（屏幕阅读器用它做地标跳转），内层
 * `role="tablist"` 不再重复同一个 `aria-label`。两层同名会让读屏把同一个名字念
 * 两遍（"一级功能模块 导航" 紧接 "一级功能模块 选项卡列表"），而 tablist 本来
 * 就嵌在这个已命名的地标里。
 */
export default function TabBar({
  items,
  activeId,
  onSelect,
  label,
  panelId,
}) {
  const tabRefs = useRef(new Map())

  function moveTab(event, index) {
    let nextIndex
    if (event.key === 'Home') nextIndex = 0
    else if (event.key === 'End') nextIndex = items.length - 1
    else if (STEP_KEYS[event.key]) {
      nextIndex = (index + STEP_KEYS[event.key] + items.length) % items.length
    } else {
      return
    }

    event.preventDefault()
    const nextItem = items[nextIndex]
    onSelect(nextItem)
    requestAnimationFrame(() => tabRefs.current.get(nextItem.id)?.focus())
  }

  return (
    <nav aria-label={label}>
      <div role="tablist" className="tabs tabs--primary">
        {items.map((item, index) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            className="tabs__tab"
            aria-selected={activeId === item.id}
            aria-controls={panelId}
            tabIndex={activeId === item.id ? 0 : -1}
            ref={(element) => {
              if (element) tabRefs.current.set(item.id, element)
              else tabRefs.current.delete(item.id)
            }}
            onClick={() => onSelect(item)}
            onKeyDown={(event) => moveTab(event, index)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </nav>
  )
}
