import Icon from './ui/Icon'
import DataMeta from './DataMeta'

const STATUS_MESSAGES = {
  loading: '正在加载数据…',
  empty: '暂无数据',
  preparing: '数据准备中，请稍后刷新。',
}

const STATUS_ICONS = {
  loading: 'clock',
  empty: 'empty',
  preparing: 'clock',
}

export default function DataState({
  state,
  message,
  stale = false,
  warnings = [],
  children,
}) {
  const metadata = <DataMeta stale={stale} warnings={warnings} />

  if (state === 'error') {
    return (
      <section className="data-state data-state--error" role="alert">
        <div className="data-state__figure">
          <span className="data-state__icon"><Icon name="alert" size={20} /></span>
          <p className="data-state__message">{message ?? '数据加载失败。'}</p>
        </div>
        {metadata}
      </section>
    )
  }

  if (state && STATUS_MESSAGES[state]) {
    return (
      <section className={`data-state data-state--${state}`} role="status">
        <div className="data-state__figure">
          <span className="data-state__icon"><Icon name={STATUS_ICONS[state]} size={20} /></span>
          <p className="data-state__message">{message ?? STATUS_MESSAGES[state]}</p>
        </div>
        {state === 'loading' && (
          <div className="data-state__skeleton" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        )}
        {metadata}
      </section>
    )
  }

  return (
    <section className="data-state data-state--content">
      {metadata}
      {children}
    </section>
  )
}
