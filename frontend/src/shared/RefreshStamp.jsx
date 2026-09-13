import Icon from './ui/Icon'

/*
 * 「更新于 HH:MM」胶囊：说明页面上这一版数据是几点几分取回来的。
 *
 * 它本来渲染在 DataMeta 里（内容区上方），2026-09-12 挪到工具栏、紧跟在日期控件
 * 右侧 —— 用户判断"我看的是哪一天的数据"和"这份数据是什么时候取回来的"是同一个
 * 动作，两者放在一起才读得通；而且发布时间随日期控件一起走，滚动内容时不会看不到。
 *
 * 只在拿到时间时渲染：首次加载中、请求失败时没有可展示的时刻，返回 null 而不是
 * 显示占位符，避免出现"更新于 --:--"这种没有信息量的胶囊。
 */
function formatRefreshTime(timestamp) {
  const date = new Date(timestamp)
  const pad = (value) => String(value).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function RefreshStamp({ refreshedAt = null }) {
  if (!refreshedAt) return null

  return (
    <span className="updated-at">
      <Icon name="clock" size={13} />
      更新于 {formatRefreshTime(refreshedAt)}
    </span>
  )
}
