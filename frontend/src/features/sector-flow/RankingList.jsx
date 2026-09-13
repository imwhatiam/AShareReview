import { formatFlowAmount } from '../../shared/stockFormat'

const DEFAULT_TOP_COUNT = 5
const MAX_RANKING_COUNT = 10

/*
 * 金额字段缺失（null / undefined / 空串 / 非数字）时一律按 0 参与排序与排行条宽度，
 * 只在展示时留破折号：`Number(undefined)` 是 NaN，一旦进了比较函数，排序结果会随
 * 引擎实现飘；`Math.abs(undefined)` 同样是 NaN，会让整张榜单的条宽一起归零。
 */
function netInflow(item) {
  const value = Number(item.latest_net_inflow)
  return Number.isFinite(value) ? value : 0
}

function sortForDirection(items, direction) {
  return [...items].sort((left, right) => (
    direction === 'inflow'
      ? netInflow(right) - netInflow(left)
      : netInflow(left) - netInflow(right)
  ))
}

export function getDefaultSelectedCodes(inflows, outflows) {
  return new Set([
    ...sortForDirection(inflows, 'inflow').slice(0, DEFAULT_TOP_COUNT),
    ...sortForDirection(outflows, 'outflow').slice(0, DEFAULT_TOP_COUNT),
  ].map((item) => item.code))
}

/* 金额写法与折线右端标签共用 `stockFormat` 那一份；这里只决定缺失值画破折号。 */
export default function RankingList({ direction, items, selectedCodes, onToggle }) {
  const title = direction === 'inflow' ? '资金流入排行' : '资金流出排行'
  const sortedItems = sortForDirection(items, direction).slice(0, MAX_RANKING_COUNT)
  const maxMagnitude = sortedItems.reduce(
    (max, item) => Math.max(max, Math.abs(netInflow(item))),
    0,
  )

  return (
    <fieldset className={`ranking ranking--${direction}`}>
      <legend className="ranking__legend">{title}</legend>
      <ul className="ranking__list">
        {sortedItems.map((item, index) => (
          <li key={item.code}>
            <label className="ranking__row">
              <span className="ranking__rank">{index + 1}</span>
              <input
                type="checkbox"
                className="ranking__checkbox"
                checked={selectedCodes.has(item.code)}
                onChange={() => onToggle(item.code)}
              />
              <span
                className="ranking__bar"
                style={{ width: `${maxMagnitude ? (Math.abs(netInflow(item)) / maxMagnitude) * 100 : 0}%` }}
              />
              <span className="ranking__name">{item.name}</span>
              <span className="ranking__value">{formatFlowAmount(item.latest_net_inflow) ?? '—'}</span>
            </label>
          </li>
        ))}
      </ul>
    </fieldset>
  )
}
