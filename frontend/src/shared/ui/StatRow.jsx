/* 单一指标行：整行文案保持在一个元素内，便于摘录与朗读。 */
export default function StatRow({ tone = 'neutral', children }) {
  const classes = [
    'stat-row',
    tone === 'up' ? 'stat-row--up' : '',
    tone === 'down' ? 'stat-row--down' : '',
  ].filter(Boolean).join(' ')

  return <p className={classes}>{children}</p>
}
