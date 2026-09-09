import { useState } from 'react'

import DataState from '../../shared/DataState'
import MomentumChart from './MomentumChart'
import useSectorMomentum from './useSectorMomentum'

const METRICS = [
  ['above_5pct', '涨幅超过 5%'],
  ['top_5_percent', '全市场涨幅前 5%'],
]

function percent(value) {
  return `${(Number(value) * 100).toFixed(2)}%`
}

function MetricSection({ metric, title, rankings, expanded, onToggle }) {
  return (
    <section aria-label={title}>
      <h2>{title}</h2>
      {rankings.length === 0 ? <p>暂无行业排行</p> : <>
        <MomentumChart rankings={rankings} />
        <ol>
          {rankings.map((item) => {
            const key = `${metric}:${item.industry_code}`
            const isExpanded = expanded.has(key)
            return (
              <li key={key}>
                <h3>{item.rank}. {item.industry_name}（评分：{Number(item.score).toFixed(4)}）</h3>
                <p>股票数：{item.stock_count}；平均涨幅：{Number(item.average_change_percent).toFixed(2)}%；成交额占比：{percent(item.market_turnover_ratio)}</p>
                <button type="button" onClick={() => onToggle(key)}>
                  {isExpanded ? '收起股票明细' : '展开股票明细'}
                </button>
                {isExpanded && (
                  <ul aria-label={`${item.industry_name}股票明细`}>
                    {(item.stocks ?? []).map((stock) => (
                      <li key={stock.code}>{stock.code} {stock.name}：{Number(stock.change_percent).toFixed(2)}%，{(Number(stock.turnover) / 1e8).toFixed(2)} 亿元</li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ol>
      </>}
    </section>
  )
}

export default function SectorMomentumPage({ apiClient }) {
  const [date, setDate] = useState('')
  const [expanded, setExpanded] = useState(new Set())
  const { phase, envelope } = useSectorMomentum({ apiClient, date })

  function toggleExpanded(key) {
    setExpanded((previous) => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (phase === 'loading') return <DataState state="loading" />
  if (phase === 'error') return <DataState state="error" message="板块动量数据暂时无法加载。" />
  if (envelope?.error?.code === 'DATA_PREPARING') return <DataState state="preparing" />
  if (envelope?.error?.code === 'DATA_NOT_AVAILABLE' || !envelope?.data) return <DataState state="empty" />

  const unmappedWarning = envelope.data.unmapped_stock_count
    ? `${envelope.data.unmapped_stock_count} 只有效股票未映射到开盘啦父行业。`
    : null
  const warnings = envelope.warnings?.length ? envelope.warnings : (unmappedWarning ? [unmappedWarning] : [])

  return (
    <DataState
      businessDate={envelope.business_date}
      dataVersion={envelope.data_version}
      stale={envelope.stale}
      partial={envelope.status === 'partial'}
      warnings={warnings}
    >
      <section aria-label="板块动量">
        <h1>板块动量</h1>
        <label htmlFor="sector-momentum-date">数据日期</label>
        <input id="sector-momentum-date" type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        <p>全市场成交额：{(Number(envelope.data.total_market_turnover) / 1e8).toFixed(2)} 亿元</p>
        {METRICS.map(([metric, title]) => (
          <MetricSection
            key={metric}
            metric={metric}
            title={title}
            rankings={envelope.data.rankings?.[metric] ?? []}
            expanded={expanded}
            onToggle={toggleExpanded}
          />
        ))}
      </section>
    </DataState>
  )
}
