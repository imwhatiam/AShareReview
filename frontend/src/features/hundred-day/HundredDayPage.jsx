import { useState } from 'react'

import DataState from '../../shared/DataState'
import RatioTrendChart from './RatioTrendChart'
import useHundredDay from './useHundredDay'

function percent(value) {
  return value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`
}

function sortByCount(items, countKey) {
  return [...items]
    .filter((item) => Number(item[countKey]) > 0)
    .sort((left, right) => Number(right[countKey]) - Number(left[countKey]) || (
      left.industry_code > right.industry_code ? 1 : -1
    ))
}

function IndustryRanking({ title, items, countKey, stocksKey, expanded, onToggle }) {
  if (items.length === 0) {
    return (
      <section aria-label={title}>
        <h2>{title}</h2>
        <p>暂无{title}</p>
      </section>
    )
  }

  return (
    <section aria-label={title}>
      <h2>{title}</h2>
      <ol>
        {items.map((item) => {
          const key = `${countKey}:${item.industry_code}`
          const isExpanded = expanded.has(key)
          const stocks = item[stocksKey] ?? []
          return (
            <li key={key}>
              <h3>{item.industry_name}（{item[countKey]}）</h3>
              <p>有效股票：{item.stock_count} 只</p>
              <button type="button" onClick={() => onToggle(key)}>
                {isExpanded ? '收起股票明细' : '展开股票明细'}
              </button>
              {isExpanded && (
                <ul aria-label={`${item.industry_name}${title}股票明细`}>
                  {stocks.length === 0 ? <li>暂无股票明细</li> : stocks.map((stock) => (
                    <li key={stock.code}>{stock.code} {stock.name}</li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

export default function HundredDayPage({ apiClient }) {
  const [date, setDate] = useState('')
  const [expanded, setExpanded] = useState(new Set())
  const { phase, envelope } = useHundredDay({ apiClient, date })

  function toggleExpanded(key) {
    setExpanded((previous) => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (phase === 'loading') return <DataState state="loading" />
  if (phase === 'error') return <DataState state="error" message="百日新高新低数据暂时无法加载。" />
  if (envelope?.error?.code === 'DATA_PREPARING') return <DataState state="preparing" />
  if (envelope?.error?.code === 'INSUFFICIENT_HISTORY') {
    return <DataState state="empty" message="历史数据不足，无法计算百日指标" />
  }
  if (envelope?.error?.code === 'DATA_NOT_AVAILABLE' || !envelope?.data) {
    return <DataState state="empty" />
  }

  const { totals, industry_summaries: summaries = [], trend = [] } = envelope.data
  const highRankings = sortByCount(summaries, 'new_high_count')
  const lowRankings = sortByCount(summaries, 'new_low_count')

  return (
    <DataState
      businessDate={envelope.business_date}
      dataVersion={envelope.data_version}
      stale={envelope.stale}
      partial={envelope.status === 'partial'}
      warnings={envelope.warnings}
    >
      <section aria-label="百日新高新低占比">
        <h1>百日新高新低占比</h1>
        <label htmlFor="hundred-day-date">数据日期</label>
        <input
          id="hundred-day-date"
          type="date"
          value={date}
          onChange={(event) => setDate(event.target.value)}
        />
        <p>有效股票：{totals.valid_stock_count} 只</p>
        <p>新高：{totals.new_high_count} 只（{percent(totals.new_high_ratio)}）</p>
        <p>新低：{totals.new_low_count} 只（{percent(totals.new_low_ratio)}）</p>
        <RatioTrendChart trend={trend} />
        <IndustryRanking
          title="新高行业排行"
          items={highRankings}
          countKey="new_high_count"
          stocksKey="new_high_stocks"
          expanded={expanded}
          onToggle={toggleExpanded}
        />
        <IndustryRanking
          title="新低行业排行"
          items={lowRankings}
          countKey="new_low_count"
          stocksKey="new_low_stocks"
          expanded={expanded}
          onToggle={toggleExpanded}
        />
      </section>
    </DataState>
  )
}
