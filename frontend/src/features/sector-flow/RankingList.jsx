const DEFAULT_TOP_COUNT = 5
const MAX_RANKING_COUNT = 25

function sortForDirection(items, direction) {
  return [...items].sort((left, right) => (
    direction === 'inflow'
      ? right.latest_net_inflow - left.latest_net_inflow
      : left.latest_net_inflow - right.latest_net_inflow
  ))
}

export function getDefaultSelectedCodes(inflows, outflows) {
  return new Set([
    ...sortForDirection(inflows, 'inflow').slice(0, DEFAULT_TOP_COUNT),
    ...sortForDirection(outflows, 'outflow').slice(0, DEFAULT_TOP_COUNT),
  ].map((item) => item.code))
}

export default function RankingList({ direction, items, selectedCodes, onToggle }) {
  const title = direction === 'inflow' ? '资金流入排行' : '资金流出排行'
  const sortedItems = sortForDirection(items, direction).slice(0, MAX_RANKING_COUNT)

  return (
    <fieldset>
      <legend>{title}</legend>
      {sortedItems.map((item) => (
        <label key={item.code}>
          <input
            type="checkbox"
            checked={selectedCodes.has(item.code)}
            onChange={() => onToggle(item.code)}
          />
          {item.name}（{item.latest_net_inflow > 0 ? '+' : ''}{item.latest_net_inflow.toFixed(1)}亿）
        </label>
      ))}
    </fieldset>
  )
}
