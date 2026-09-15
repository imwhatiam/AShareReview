import { useState } from 'react'

import { resolveDataStateName } from '../../shared/dataStateName'
import { resolveDisplayDate } from '../../shared/businessDate'
import {
  formatDecimal,
  formatRatioPercent,
  formatTurnoverInYi,
  stockLabel,
} from '../../shared/stockFormat'
import useToggleSet from '../../shared/useToggleSet'
import DatePicker from '../../shared/ui/DatePicker'
import ModulePage from '../../shared/ui/ModulePage'
import Panel from '../../shared/ui/Panel'
import RankItem from '../../shared/ui/RankItem'
import RefreshStamp from '../../shared/RefreshStamp'
import StatRow from '../../shared/ui/StatRow'
import MomentumChart from './MomentumChart'
import useSectorMomentum from './useSectorMomentum'

const METRICS = [
  ['above_5pct', '涨幅超过 5%'],
  ['top_5_percent', '全市场涨幅前 5%'],
]

const ERROR_MESSAGE = '板块动量数据暂时无法加载。'

/*
 * 本页所有数字都走 `stockFormat` 的共享写法（缺失值留破折号）。这里曾经自带一个
 * 没有 null 守卫的 `percent()`：字段缺失时显示 `NaN%`，而同样的比率在百日页显示
 * `—` —— 同一份后端契约在两个页面上有两种呈现。
 */

function MetricSection({ metric, title, rankings, expanded, onToggle }) {
  return (
    <Panel title={title} icon="pulse">
      {rankings.length === 0 ? (
        <p className="empty-note">暂无行业排行</p>
      ) : (
        <div className="module-stack">
          <div className="chart-frame">
            <MomentumChart rankings={rankings} />
          </div>
          <ol className="rank-list">
            {rankings.map((item) => {
              const key = `${metric}:${item.industry_code}`
              return (
                <RankItem
                  key={key}
                  index={item.rank}
                  title={`${item.industry_name}（评分：${formatDecimal(item.score, 4)}）`}
                  facts={(
                    <>
                      <span>股票数：{item.stock_count}</span>
                      <span>平均涨幅：{formatDecimal(item.average_change_percent)}%</span>
                      <span>成交额占比：{formatRatioPercent(item.market_turnover_ratio)}</span>
                    </>
                  )}
                  expanded={expanded.has(key)}
                  onToggle={() => onToggle(key)}
                  detailLabel={`${item.industry_name}股票明细`}
                >
                  {(item.stocks ?? []).map((stock) => (
                    <li key={stock.code} className="stock-detail__item">
                      {stockLabel(stock)}
                    </li>
                  ))}
                </RankItem>
              )
            })}
          </ol>
        </div>
      )}
    </Panel>
  )
}

export default function SectorMomentumPage({ apiClient }) {
  const [date, setDate] = useState('')
  const { values: expanded, toggle: toggleExpanded } = useToggleSet()
  const { phase, envelope, updatedAt, refresh } = useSectorMomentum({ apiClient, date })

  /*
   * 本页不展示告警列表：后端唯一会发的告警是「N 只有效股票未映射到开盘啦板块」，
   * 那是上游行业映射的覆盖度说明，用户无法处理且每次都会出现；未映射数量仍在
   * envelope.data.unmapped_stock_count 里，需要时可以查。旧数据提示（stale）保留。
   * 之前这里还按 unmapped_stock_count 再拼一条同样的文案，与后端告警重复，已删除。
   */
  const data = envelope?.data ?? null
  const stateName = resolveDataStateName(phase, envelope, { hasContent: Boolean(data) })
  const displayDate = resolveDisplayDate(date, envelope)

  return (
    <ModulePage
      envelope={envelope}
      stateName={stateName}
      message={stateName === 'error' ? ERROR_MESSAGE : undefined}
      showWarnings={false}
      toolbar={(
        <>
          <DatePicker id="sector-momentum-date" value={displayDate} onChange={setDate} />
          <RefreshStamp updatedAt={updatedAt} onRefresh={refresh} />
          {/* 成交额依赖数据，没数据时整组不渲染。 */}
          {data && (
            <div className="stat-grid">
              <StatRow>全市场成交额：{formatTurnoverInYi(data.total_market_turnover)} 亿元</StatRow>
            </div>
          )}
        </>
      )}
    >
      {/* 两个口径并排一行，方便左右对照同一批行业。 */}
      <div className="pair-grid">
        {METRICS.map(([metric, title]) => (
          <MetricSection
            key={metric}
            metric={metric}
            title={title}
            rankings={data?.rankings?.[metric] ?? []}
            expanded={expanded}
            onToggle={toggleExpanded}
          />
        ))}
      </div>
    </ModulePage>
  )
}
