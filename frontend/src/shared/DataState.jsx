import DataMeta from './DataMeta'

const STATUS_MESSAGES = {
  loading: '正在加载数据…',
  empty: '暂无数据',
  preparing: '数据准备中，请稍后刷新。',
}

export default function DataState({
  state,
  message,
  businessDate,
  dataVersion,
  stale = false,
  partial = false,
  warnings = [],
  children,
}) {
  if (state === 'error') {
    return (
      <section className="data-state data-state--error" role="alert">
        <p>{message ?? '数据加载失败。'}</p>
        <DataMeta
          businessDate={businessDate}
          dataVersion={dataVersion}
          stale={stale}
          partial={partial}
          warnings={warnings}
        />
      </section>
    )
  }

  if (state && STATUS_MESSAGES[state]) {
    return (
      <section className={`data-state data-state--${state}`} role="status">
        <p>{message ?? STATUS_MESSAGES[state]}</p>
        <DataMeta
          businessDate={businessDate}
          dataVersion={dataVersion}
          stale={stale}
          partial={partial}
          warnings={warnings}
        />
      </section>
    )
  }

  return (
    <section className="data-state data-state--content">
      <DataMeta
        businessDate={businessDate}
        dataVersion={dataVersion}
        stale={stale}
        partial={partial}
        warnings={warnings}
      />
      {children}
    </section>
  )
}
