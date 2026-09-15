import { useState } from 'react'

import { resolveDataStateName } from '../../shared/dataStateName'
import { resolveDisplayDate } from '../../shared/businessDate'
import RefreshStamp from '../../shared/RefreshStamp'
import { formatRatioPercent, stockLabel } from '../../shared/stockFormat'
import useToggleSet from '../../shared/useToggleSet'
import DatePicker from '../../shared/ui/DatePicker'
import ModulePage from '../../shared/ui/ModulePage'
import Panel from '../../shared/ui/Panel'
import RankItem from '../../shared/ui/RankItem'
import StatRow from '../../shared/ui/StatRow'
import RatioTrendChart from './RatioTrendChart'
import useHundredDay from './useHundredDay'

const MAX_RANKINGS = 10

const ERROR_MESSAGE = '百日新高新低数据暂时无法加载。'
/*
 * 该日期之前的行情不足 199 个交易日 → 404，缺的是更早的历史，永远不会自愈，
 * 因此要给出具体原因而不是通用空态。
 */
const INSUFFICIENT_HISTORY = 'INSUFFICIENT_HISTORY'
const EMPTY_MESSAGE = '历史数据不足，无法计算百日指标'

/* 按新高（或新低）数量降序取前 10 个行业；数量为 0 的行业不上榜。 */
function topIndustries(items, countKey) {
  return [...items]
    .filter((item) => Number(item[countKey]) > 0)
    .sort((left, right) => Number(right[countKey]) - Number(left[countKey]) || (
      left.industry_code > right.industry_code ? 1 : -1
    ))
    .slice(0, MAX_RANKINGS)
}

/*
 * 明细按当日涨跌幅排序，方向由 direction 决定：
 * - `desc`（新高排行）：高的在前，涨幅大的排前面。
 * - `asc`（新低排行）：低的在前 —— 也就是"跌得多的排前面"，-18.33% 排在 -8.37% 之前。
 * 没有当日行情的股票（change_percent 为 null，例如当天停牌）永远排最后 ——
 * 不能因为排序把它们丢掉；同涨跌幅再按代码升序，保证顺序稳定。
 */
function sortByChange(stocks, direction) {
  const sign = direction === 'asc' ? -1 : 1
  return [...stocks].sort((left, right) => {
    const leftValue = left.change_percent == null ? null : Number(left.change_percent)
    const rightValue = right.change_percent == null ? null : Number(right.change_percent)
    if (leftValue === null || rightValue === null) {
      if (leftValue === rightValue) return 0
      return leftValue === null ? 1 : -1
    }
    return (rightValue - leftValue) * sign || (left.code > right.code ? 1 : -1)
  })
}

function IndustryRanking({
  title,
  items,
  countKey,
  stocksKey,
  expanded,
  onToggle,
  stockSort = 'desc',
}) {
  if (items.length === 0) {
    return (
      <Panel title={title}>
        <p className="empty-note">暂无{title}</p>
      </Panel>
    )
  }

  return (
    <Panel title={title}>
      <ol className="rank-list">
        {items.map((item, index) => {
          const key = `${countKey}:${item.industry_code}`
          const stocks = item[stocksKey] ?? []
          return (
            <RankItem
              key={key}
              index={index + 1}
              title={`${item.industry_name}（${item[countKey]}）`}
              facts={<span>有效股票：{item.stock_count} 只</span>}
              expanded={expanded.has(key)}
              onToggle={() => onToggle(key)}
              detailLabel={`${item.industry_name}${title}股票明细`}
            >
              {stocks.length === 0 ? (
                <li className="stock-detail__item">暂无股票明细</li>
              ) : sortByChange(stocks, stockSort).map((stock) => (
                <li key={stock.code} className="stock-detail__item">
                  {stockLabel(stock)}
                </li>
              ))}
            </RankItem>
          )
        })}
      </ol>
    </Panel>
  )
}

/*
 * 内容区提示语：失败给通用文案，「行情不足」给具体原因，其余交给 DataState 的默认文案。
 */
function stateMessage(stateName, envelope) {
  if (stateName === 'error') return ERROR_MESSAGE
  if (envelope?.error?.code === INSUFFICIENT_HISTORY) return EMPTY_MESSAGE
  return undefined
}

export default function HundredDayPage({ apiClient }) {
  const [date, setDate] = useState('')
  const { values: expanded, toggle: toggleExpanded } = useToggleSet()
  const { phase, envelope, updatedAt, refresh } = useHundredDay({ apiClient, date })

  const data = envelope?.data ?? null
  const stateName = resolveDataStateName(phase, envelope, {
    hasContent: Boolean(data),
    // 「行情不足 199 个交易日」也是空态，只是要给出具体原因。
    emptyCodes: [INSUFFICIENT_HISTORY],
  })
  const displayDate = resolveDisplayDate(date, envelope)
  const totals = data?.totals ?? null

  return (
    <ModulePage
      envelope={envelope}
      stateName={stateName}
      message={stateMessage(stateName, envelope)}
      toolbar={(
        <>
          <DatePicker id="hundred-day-date" value={displayDate} onChange={setDate} />
          <RefreshStamp updatedAt={updatedAt} onRefresh={refresh} />
          {/* 三个汇总指标依赖数据，没数据时整组不渲染。 */}
          {totals && (
            <div className="stat-grid">
              <StatRow>有效股票：{totals.valid_stock_count} 只</StatRow>
              <StatRow tone="up">新高：{totals.new_high_count} 只（{formatRatioPercent(totals.new_high_ratio)}）</StatRow>
              <StatRow tone="down">新低：{totals.new_low_count} 只（{formatRatioPercent(totals.new_low_ratio)}）</StatRow>
            </div>
          )}
        </>
      )}
    >
      <Panel title="占比趋势">
        <div className="chart-frame">
          <RatioTrendChart trend={data?.trend ?? []} />
        </div>
      </Panel>

      {/* 两个排行并排一行，各显示前 10 个行业，方便左右对照。 */}
      <div className="pair-grid">
        <IndustryRanking
          title="新高行业排行"
          items={topIndustries(data?.industry_summaries ?? [], 'new_high_count')}
          countKey="new_high_count"
          stocksKey="new_high_stocks"
          expanded={expanded}
          onToggle={toggleExpanded}
          stockSort="desc"
        />
        <IndustryRanking
          title="新低行业排行"
          items={topIndustries(data?.industry_summaries ?? [], 'new_low_count')}
          countKey="new_low_count"
          stocksKey="new_low_stocks"
          expanded={expanded}
          onToggle={toggleExpanded}
          stockSort="asc"
        />
      </div>
    </ModulePage>
  )
}
