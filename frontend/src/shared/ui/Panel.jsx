import Icon from './Icon'

/*
 * 全站唯一的区块容器：标题 / 正文。
 * 默认渲染为带 aria-label 的 <section>，保留 region 语义。
 *
 * 2026-09-12 清理：删掉了从未被使用的 `actions`（右上角操作区）与 `flush`
 * （去内边距）两个 prop。页面级的操作按钮都在工具栏里，不在 panel 头部；
 * 真要加回来时，记得同时补 `.panel__actions` / `.panel--flush` 的样式。
 *
 * 2026-09-13 清理：`className`（全仓 0 处传入）与 `headingLevel`（5 处调用全部显式
 * 传默认值 2）一并删除。标题层级固定为 h2，`panel` 类名不再由外部拼接。
 */
export default function Panel({ title, icon, children }) {
  return (
    <section className="panel" aria-label={typeof title === 'string' ? title : undefined}>
      {title && (
        <header className="panel__head">
          <h2 className="panel__title">
            {icon && <span className="panel__title-icon"><Icon name={icon} size={16} /></span>}
            {title}
          </h2>
        </header>
      )}
      <div className="panel__body">{children}</div>
    </section>
  )
}
