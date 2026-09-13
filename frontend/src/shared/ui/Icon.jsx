/*
 * 统一的线性图标集。所有图标基于 24×24 网格、相同描边宽度，
 * 默认继承 currentColor，并且不带任何文本，保证无障碍名称只来自业务文案。
 *
 * 只保留有调用方的名字：一级 Tab 的左侧图标已于 2026-09-12 移除，原先为它准备的
 * `flow` / `list` / `calendar` 也已一并删除，需要时按同一 24×24 网格重新画。
 *
 * 2026-09-13：删掉了 `strokeWidth`（全仓 0 处传入）与 `stroke`（2 处调用传的都是
 * 默认值 `currentColor`）。描边宽度与颜色固定为下面的常量，不再由调用方拼。
 */

const STROKE_WIDTH = 1.7

const PATHS = {
  // 板块动量
  pulse: <path d="M3 12h3.5l2.5-6 4 12 2.5-6H21" />,
  copy: (
    <>
      <rect x="9" y="9" width="11.5" height="11.5" rx="2.5" />
      <path d="M5 15.5V6.5a2 2 0 0 1 2-2h9" />
    </>
  ),
  alert: (
    <>
      <path d="M12 4.5 21 20H3l9-15.5Z" />
      <path d="M12 10.5v4M12 17.5h.01" />
    </>
  ),
  empty: (
    <>
      <path d="M4 8.5 12 4.5l8 4v7l-8 4-8-4v-7Z" />
      <path d="M9.5 12h5" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5v5l3 2" />
    </>
  ),
  chevron: <path d="M9.5 5.5 16 12l-6.5 6.5" />,
  brand: <path d="M4 17.5 9 8l3.5 6.5L16 10l4 7.5" />,
}

export default function Icon({ name, className, size = 18 }) {
  const path = PATHS[name]
  if (!path) {
    return null
  }

  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={STROKE_WIDTH}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {path}
    </svg>
  )
}
