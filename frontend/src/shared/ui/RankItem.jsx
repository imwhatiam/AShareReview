import Icon from './Icon'

/*
 * 排行榜单条：序号 + 标题 + 事实标签 + 展开按钮 + 明细列表。
 *
 * 明细内容由调用方决定 —— 百日页要按当日涨跌幅排序、给空明细兜底，动量页直接按
 * 后端顺序列出 —— 本组件只负责这条卡片的结构与展开交互。
 */
export default function RankItem({
  index,
  title,
  facts,
  expanded,
  onToggle,
  detailLabel,
  children,
}) {
  return (
    <li className="rank-item">
      <div className="rank-item__head">
        <span className="rank-item__index">{index}</span>
        <h3 className="rank-item__title">{title}</h3>
        <div className="rank-item__facts">{facts}</div>
      </div>
      <button type="button" className="btn btn--sm detail-toggle" onClick={onToggle}>
        {expanded ? '收起股票明细' : '展开股票明细'}
        <Icon
          name="chevron"
          size={14}
          className={expanded ? 'detail-toggle__icon is-open' : 'detail-toggle__icon'}
        />
      </button>
      {expanded && (
        <ul className="stock-detail stock-detail--inline" aria-label={detailLabel}>
          {children}
        </ul>
      )}
    </li>
  )
}
