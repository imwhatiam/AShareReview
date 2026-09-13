/*
 * 大涨跌幅与大成交量个股看板。
 *
 * 版面是二维的：行 = 市场（上证 / 深证 / 北交所），列 = 方向（涨 / 跌）。
 * 每只股票压缩成一枚圆角胶囊，只留名称、涨跌幅和成交额；股票代码不上屏，
 * 开盘啦板块改由 title 悬浮提示承载 —— 悬浮提示用原生 title 而不是 CSS 伪元素，
 * 因为外层 .panel 是 overflow: hidden，绝对定位的伪元素在面板边缘会被裁掉。
 */

import { formatChangePercent, formatTurnover } from '../../shared/stockFormat'

const MARKETS = [
  { key: 'sse', label: '上证', rise: 'sse_rise', fall: 'sse_fall' },
  { key: 'szse', label: '深证', rise: 'szse_rise', fall: 'szse_fall' },
  // 北交所有股票才渲染，没有时不留一个空行占位。
  { key: 'bse', label: '北交所', rise: 'bse_rise', fall: 'bse_fall', hideWhenEmpty: true },
]

const UP_TITLE = '涨幅超8% 成交超8亿'
const DOWN_TITLE = '跌幅超8% 成交超8亿'

function industryTooltip(industries) {
  const names = (industries ?? []).map((industry) => industry.name)
  return names.length === 0 ? '板块：—' : `板块：${names.join('、')}`
}

function StockPill({ item, tone }) {
  return (
    <li
      className={`move-pill move-pill--${tone}`}
      title={industryTooltip(item.industries)}
    >
      <span className="move-pill__name">{item.name}</span>
      <span className="move-pill__facts">
        {`(${formatChangePercent(item.change_percent)}, ${formatTurnover(item.turnover)})`}
      </span>
    </li>
  )
}

function MoveHalf({ label, items, tone }) {
  // 没有符合条件的个股时整栏留白，不渲染"暂无…"占位文案：看板的行列由市场行撑住，
  // 空栏安静留空比一句提示更干净，也不会在密集页面上制造噪音。
  return (
    <section className="move-half" role="region" aria-label={label}>
      {items.length > 0 && (
        <ul className="move-list">
          {items.map((item) => (
            <StockPill key={item.code} item={item} tone={tone} />
          ))}
        </ul>
      )}
    </section>
  )
}

export default function StockMoveBoard({ groups }) {
  return (
    <div className="move-board">
      <div className="move-board__head">
        {/* 与行标签同宽的占位格：让两个列标题正好落在各自的半区上方。 */}
        <span className="move-board__gutter" aria-hidden="true" />
        <h3 className="move-board__title move-board__title--up">{UP_TITLE}</h3>
        <h3 className="move-board__title move-board__title--down">{DOWN_TITLE}</h3>
      </div>

      {MARKETS.map((market) => {
        const riseItems = groups[market.rise] ?? []
        const fallItems = groups[market.fall] ?? []
        if (market.hideWhenEmpty && riseItems.length === 0 && fallItems.length === 0) {
          return null
        }
        return (
          <div className="move-row" key={market.key}>
            <h3 className="move-row__label">{market.label}</h3>
            <MoveHalf label={`${market.label}上涨`} items={riseItems} tone="up" />
            <MoveHalf label={`${market.label}下跌`} items={fallItems} tone="down" />
          </div>
        )
      })}
    </div>
  )
}
