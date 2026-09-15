import Icon from './ui/Icon'

/*
 * 「更新于 HH:MM」胶囊 —— 同时是**刷新当前页面数据的唯一入口**（2026-09-14 起）。
 *
 * 它本来只是个说明：页面上这一版数据是几点几分取回来的。那时数据靠定时器自己更新
 * （资金流 5 分钟、其余三页 30 分钟），用户没有"现在就去取一次"的办法。自动重取删掉
 * 之后，这个时刻就成了最自然的刷新按钮：它本来就在说"这是什么时候取回来的"，
 * 点它一下就是"现在再取一次"。
 *
 * **时刻的含义是"库里这份数据是什么时候写的"**，来自信封的 `data_updated_at`
 * （`useResource` 透传过来），**不是浏览器发请求的时刻**。结果行落库后一直躺在库里，
 * 页面随时打开，两者可以差好几个小时 —— 用户想知道的是"我看到的数字有多新"，所以
 * 显示的必须是数据自己的时间。
 *
 * 所以它是一颗 `<button>` 而不是 `<span>`：能聚焦、能回车触发、能被读屏读成按钮，
 * 鼠标移上去是手型（`cursor: pointer`）。它渲染在工具栏、紧跟在日期控件右侧 ——
 * 用户判断"我看的是哪一天的数据"和"这份数据是什么时候写进库的"是同一个动作，
 * 两者放在一起才读得通；而且它随日期控件一起走，滚动内容时不会看不到。
 *
 * 只在不缺时刻时渲染：首次加载中、请求失败、以及"这一天还没有数据"的空态都没有
 * 可展示的时刻，返回 null 而不是显示占位符，避免出现"更新于 --:--"或者拿一个
 * 假的当前时间冒充数据时间。这些状态下日期控件照旧可用，改日期或刷新页面即可重来。
 *
 * 文案必须是同一个元素里的直接文本子节点（`更新于 ` + 时刻）：测试用整句匹配它，
 * 把时刻包进子元素会切断这层文本。
 */
function formatUpdatedAt(value) {
  const date = new Date(value)
  const pad = (number) => String(number).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function RefreshStamp({ updatedAt = null, onRefresh }) {
  if (!updatedAt) return null

  const time = formatUpdatedAt(updatedAt)

  return (
    <button
      type="button"
      className="updated-at"
      onClick={onRefresh}
      title="点击刷新当前页面的数据"
    >
      <Icon name="clock" size={13} />
      更新于 {time}
    </button>
  )
}
