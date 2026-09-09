function formatChangePercent(value) {
  const number = Number(value)
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

function formatTurnover(value) {
  return `${(Number(value) / 1e8).toFixed(2)} 亿元`
}

export default function StockGroupTable({ title, items }) {
  return (
    <section aria-label={title}>
      <h3>{title}（{items.length}）</h3>
      {items.length === 0 ? (
        <p>暂无符合条件的个股</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">代码</th>
              <th scope="col">名称</th>
              <th scope="col">涨跌幅</th>
              <th scope="col">成交额</th>
              <th scope="col">父行业</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.code}>
                <td>{item.code}</td>
                <td>{item.name}</td>
                <td>{formatChangePercent(item.change_percent)}</td>
                <td>{formatTurnover(item.turnover)}</td>
                <td>{(item.parent_industries ?? []).map((industry) => industry.name).join('、') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
