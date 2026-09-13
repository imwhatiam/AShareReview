import Icon from './ui/Icon'

/*
 * 数据状态说明：只在真有必要提示时出现，不再展示业务日期与数据版本。
 * 已删除「部分数据」chip：后端 status='partial' 完全由「warnings 非空」推导
 * （见 core/api/responses.py），它和紧随其后的告警列表说的是同一件事，
 * 同时出现只是把同一条信息显示了两遍。
 * 「更新于 HH:MM」也已从这里移出：它现在由 shared/RefreshStamp 渲染在工具栏的
 * 日期控件右侧，与"在看哪一天的数据"挨着（见该组件注释）。
 */
export default function DataMeta({ stale = false, warnings = [] }) {
  const hasMetadata = stale || warnings.length > 0
  if (!hasMetadata) {
    return null
  }

  return (
    <aside className="data-meta" aria-label="数据状态说明">
      {stale && <span className="data-meta__chip data-meta__stale">正在展示旧数据</span>}
      {warnings.length > 0 && (
        <ul className="data-meta__warnings">
          {warnings.map((warning) => (
            <li key={warning} className="data-meta__warning">
              <Icon name="alert" size={14} />
              {warning}
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
