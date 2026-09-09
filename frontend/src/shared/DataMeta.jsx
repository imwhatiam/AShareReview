export default function DataMeta({
  businessDate,
  dataVersion,
  stale = false,
  partial = false,
  warnings = [],
}) {
  const hasMetadata = businessDate || dataVersion || stale || partial || warnings.length > 0
  if (!hasMetadata) {
    return null
  }

  return (
    <aside className="data-meta" aria-label="数据状态说明">
      {businessDate && <span>业务日期：{businessDate}</span>}
      {dataVersion && <span>数据版本：{dataVersion}</span>}
      {stale && <span className="data-meta__stale">正在展示旧数据</span>}
      {partial && <span className="data-meta__partial">部分数据</span>}
      {warnings.length > 0 && (
        <ul>
          {warnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
      )}
    </aside>
  )
}
