import DataState from '../DataState'
import Panel from './Panel'

/*
 * 四个数据页共用的外壳：DataState（旧数据 / 告警元信息）→ Panel → module-stack
 * → 工具栏 → 数据状态或内容。
 *
 * 工具栏在所有数据状态下都保留（其中依赖数据的部分由各页自己决定渲染与否）。
 * 整页替换会让日期控件被卸载重建：用户刚选完日期，弹层、焦点和滚动位置全丢，
 * 页面还会先塌成一行提示再弹回来。板块资金流页一直是这个约定，其余三页照做。
 *
 * `children` 在内容区渲染，`stateName` 非空时被替换成对应的 DataState；调用方因此
 * 会在两种情况下都构造 children，读取信封数据时请用可选链（`data?.trend`）。
 *
 * `showWarnings` 默认开启。板块动量页显式关掉它：后端在该页只发得出「N 只有效股票
 * 未映射到开盘啦板块」这一条，属上游映射覆盖度说明，用户无法处理且每次都在。
 */
export default function ModulePage({
  envelope,
  stateName,
  message,
  toolbar,
  notice = null,
  showWarnings = true,
  children,
}) {
  return (
    <DataState
      stale={envelope?.stale}
      warnings={showWarnings ? envelope?.warnings : undefined}
    >
      <Panel>
        <div className="module-stack">
          <div className="toolbar">{toolbar}</div>
          {notice}
          {stateName
            ? <DataState state={stateName} message={message} />
            : children}
        </div>
      </Panel>
    </DataState>
  )
}
