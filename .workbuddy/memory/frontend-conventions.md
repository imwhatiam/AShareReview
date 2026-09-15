# 前端与页面文案约定（专题）

按需读取。

## 术语与页面文案

- **行业快照只有一层，没有父子层级**：中文术语按场景分两套 —— 导航/模块名/告警说**「板块」**（板块资金流、板块动量、「未映射到开盘啦板块」），分析内容说**「行业」**（新高/新低行业排行、行业动量评分图）。**英文标识符统一用 `industry`**：契约 `Industry`、`CompleteMarketSnapshot.industries`、API 响应键 **`industries`**（`stock_moves` 与 `hundred_day` 都是）—— 前端读 `item.industries`，**不是** `parent_industries`。
- **四个业务页面无页面级标题**：模块名只在左侧导航 Tab 出现（无障碍靠 `<main role="tabpanel" aria-label={display_name}>`）；模块级 `Panel` 写裸 `<Panel>`（`subtitle` prop 已删）；页面内区块标题 `headingLevel` **从 2 起算**（避免与 `App` 的 `<h1>` 跳级）。
- 页面顶部**不展示「业务日期 / 数据版本」**：`shared/DataMeta.jsx` 只留 `stale` + `warnings`；**没有 `partial` chip**（后端 `status='partial'` 完全等价于 warnings 非空，chip 与紧随其后的告警列表是同一件事）。`DataState` 没有 `businessDate`/`dataVersion`/`partial` 三个 prop，但 `envelope.business_date`/`data_version`/`status` 仍是 API 契约。
- 板块动量页**按设计不渲染 warnings**（唯一告警"N 只有效股票未映射到开盘啦板块"用户无法处理且每次都在）：数量仍在 `data.unmapped_stock_count`，`stale` 保留。个股页无独立统计块，总数写在复制按钮文案里（`共 N 只股票，全部复制`，N = `data.distinct_stock_count`）。
- 文案多集中在共享组件（`Panel` title / `SegmentedControl` legend / `DataMeta` chip / 日期控件 aria）—— **改文案先 grep 组件，不只 grep 页面文件**，一处改动即全站生效。
- 日期与窗口控件**不渲染可见标签**：日期用 `aria-label="数据日期"`（挂在触发器 button 上），窗口用 `role="group" aria-label="统计窗口"`。5 个页面测试的 `getByLabelText('数据日期')` 就靠这些 aria —— **改这两处务必保留 aria 名**，不要"清理"成无标签控件。
- 前端测试大量用 `getByText` 精确匹配整句（`getNodeText` 只拼元素直接文本子节点）：**被断言的整句文案必须保持在同一元素内**，不能拆进子元素。

## API 请求与开发期代理

- **前端没有 API 基址变量**：`src/api/client.js` 只发相对 `/api/...` 且 `credentials: 'same-origin'`，开发期完全靠 Vite 代理，生产是静态产物 + 同源反代。
- **唯一开关是仓库根 `.env` 的 `VITE_DEV_BACKEND_ORIGIN`**：`vite.config.js` 用 `envDir: '..'` + `loadEnv(mode, '..', '')` 读它，交给 `src/api/developmentProxy.js::createDevelopmentApiProxy()` 生成 `/api` 代理；空或空白 → `{}`（不代理）。**改完必须重启 `npm run dev`** —— envDir 在项目根之外，热更新不覆盖环境变量。
- **`envelopeErrorCodes` 必须是模块级常量**：它直接进 effect 依赖数组，hook 的默认值同理；调用方每次渲染换引用会造成请求风暴（测试里表现为 node OOM）。

## 日期与工具条

- 日期控件是自绘 `src/shared/ui/DatePicker.jsx`（4 个页面都用）：**原生 `input[type=date]` 的日历弹层在 UA shadow DOM 内无法改样式，禁止退回原生控件**。弹层 `position: fixed`（祖先 `.panel` 有 `overflow: hidden`，absolute 会被裁）。
- `POPOVER_ESTIMATED_HEIGHT = 336` 按**最大行数（6 行）**取，不是实测的 5 行高度（299px）—— 改成实测值会让 6 行月份在下方空间临界时"该翻转却不翻转"。
- 测试选日期一律用 `src/test/datePicker.js` 的 `pickDate(target)`（内部按月份标题导航；弹层默认停在 value 所在月，**写死月份会随运行日期漂移而挂**，别绕过它直接点格子）；读当前日期用触发器文本断言 `toHaveTextContent`，不是 `toHaveValue`。
- 日期显示值统一走 `shared/businessDate.js` 的 `resolveDisplayDate(selectedDate, envelope)`（= 手选日期 || `envelope.business_date` || ''）。四个页面曾各自实现而漂移，**新增页面一律用它**。
- 资金流页**所有统计窗口都以最近一个已存交易日为终点**：`KaipanlaPage.handleWindowChange` 点任一窗口（当日/5/10/20日）都 `setDate('')`，空 date 由后端取最新业务日期；多日窗口 = `trading_day_window(end_date, count=days)` 截止该日往回取 N 个交易日。用户显式选日期时该日期才是窗口终点。
- `.toolbar` 为 `align-items: center`：日期框 37px 与指标行 22px 高度不同，居中才不会"文字贴底、上方留空"。四个页面的"日期 + 统计/按钮"放在**同一行**；窄屏下 `.toolbar > .stat-grid` 与 `.date-picker` 都 `flex: 1 1 100%`。
- **指标行（`.stat-row`/`.stat-grid`）是纯文字**（无 padding/border/圆角/底色），`--up` 用 `--color-market-up`、`--down` 用 `--color-market-down`，只靠**文字颜色 + 字重 600** 区分；`.stat-grid` 为自然宽度 + `align-items: baseline` + `gap: var(--space-2) var(--space-5)`（等分列宽已删）。仅板块动量页与百日页在用。
- **内容区按钮一律 `.btn`**（白底 + `--color-border-strong` 描边）；实心品牌蓝 `.btn--primary` **只用于登录页提交**。
- `.segmented`（统计窗口分段控件）**无外层背景/边框**；`.segmented__item` 纵向内边距与 `.date-picker__trigger` 同为 `0.4rem`，靠这个在居中对齐下保证上下边缘齐平；激活态用 `--color-brand-50` 浅蓝底。

## 令牌与图表

- 外壳用品牌蓝，**红/绿仅表示涨跌**（红涨绿跌），不得用作操作色。`tokens.css` 必须保留互不相同的 `--color-market-up/down/error`；这条约定由 `src/styles/tokens.test.js` 按**色相**守（`up` 落在色环两端 ≈0°/360°、`down` 在 90°–170°、`error` 不等于其中任一个），**不读 CSS 文本断子串**（那只是把令牌抄一遍，两边一起改就照样通过）。该文件只读文件、不碰 DOM，因此首行是 `/* @vitest-environment node */` —— jsdom 下 `import.meta.url` 不是 file URL，`new URL('./tokens.css', import.meta.url)` 会抛 `TypeError: The URL must be of scheme file`；**别改成 CWD 相对路径**绕过，那会把用例绑死在调用目录上。
- **`index.css` 的 `:focus-visible` / `@media (max-width: 40rem)` / `overflow-x: auto` 没有任何自动化断言**（jsdom 不做层叠也不做命中测试，读文本既过严又过松）。这三处的回归只能靠 `frontend-visual-verification` 截图人眼确认，**改动它们时别指望测试兜底**。
- 图表配色只允许来自 `shared/charts/chartBaseline.js`（**四图共用基线的唯一定义处**：`CHART` / `TOOLTIP` / `GRID` / `ANIMATION_DURATION_MS` / `categoryAxis` / `valueAxis`）。布局是**三文件**：`chartBaseline.js`（共用基线）← `chartTheme.js`（**只含两个盘后模块**的构造器：`momentumOption` / `trendOption` / `scoreAxisMax` / `MOMENTUM_BARS`）与 `features/sector-flow/flowOption.js`（资金流两张图）。要改某张图就改它自己的构造器，**不要在页面里 import 调色板自己拼 option**。下沉判据是**被两个以上模块消费** —— 别为了"看起来对称"往基线搬。**红/绿严格留给涨跌方向**，衡量"强弱/规模"的图（如动量评分）用品牌蓝（`score` 色）。类目轴刻度由 `categoryAxis` 内部 `shortCategoryLabel()` 把 `2026-09-10 15:00` 显示成 `09-10`，但 **`option.xAxis.data` 必须保持原始值**（`flowView.test.jsx` 直接断言）。
- 资金流折线图（`flowOption`）**不渲染顶部图例**：板块名 + 资金净额常驻每条折线右端（`endLabel`，`formatFlowAmount()` 统一「正数带 + / 一位小数 / 亿」）。`grid` 为 `{ top: 36, right: 152 }`：`right` 是线端标签留白，标签画在 grid 右边界之外，**可用宽度 = `right` − `endLabel.distance`(6)，不够就被画布裁掉等于丢掉板块名**（最坏 7 个汉字板块名 + 三位数亿级 ≈146px，`flowView.test.jsx` 断言 ≥146；改标签文案/字号必须复查这个留白）；`top` 只需够 y 轴名称（设 20 会把轴名裁掉）。`labelLayout.moveOverlap:'shiftY'` 的最小行距**锁死在字号**（11px），给 `endLabel` 加 padding 无效。
- **分时横轴：范围恒为完整交易时段，刻度取整半点，午休两侧各自朝外对齐**。后端给的 `timePoints` 永远是 50 个五分钟槽（09:30–11:30 / 13:00–15:00），曲线只画到最后一个已采集时点（`series[].data` 比轴短），所以前端**不要**按数据长度去推轴、也不要给缺失段补值。刻度由 `isClockTick`（分钟数 % 30 == 0，共 10 个）判断，**不要按索引等间隔抽稀**：上午 09:30–11:30 是奇数个槽，按索引跨过午休会错位成 13:05…14:55。该轴必须 `hideOverlap: false` —— 抽稀按画布宽度猜，窄一点就丢掉半边的刻度，而交易时段的刻度必须始终在场。
  - **午休的 11:30 与 13:00 两个刻度都要在，且都不许叠字**（这两个时刻都会有数据）。做法是 `clockAxisData()` 把这一对**相邻的整半点**换成类目项对象 `{ value, textStyle: { align } }` —— 前一条右对齐（文本落在自己刻度左侧）、后一条左对齐（文本落在自己刻度右侧）。**ECharts 6 的类目轴支持给单个 data 项挂 `textStyle`**（`AxisBuilder` 会为它单独建一个标签 Model），这是官方途径；`axisLabel.align` 只接受字符串、**无法按项区分**。
  - 不用"合并成一条「11:30/13:00」"（等于少一个刻度），也不要交给 ECharts 防重叠抽稀（会直接丢掉 13:00）。朝外对齐的间距**恒等于一个槽宽**（与画布宽度无关），是全行最小值 —— 即整条轴唯一的紧邻对就是这一对，而它仍有可见间隙（轴上不画刻度线，标签略偏看不出）。
  - `option.xAxis.data` 仍保留**原始的 50 个刻度值与顺序**，只有午休两侧那两项裹了 `textStyle`（取值时用 `typeof item === 'string' ? item : item.value`）；`chart.convertToPixel` 与 tooltip 表头照旧拿到纯时刻。`flowView.test.jsx` 直接断言这两项的下标（24 / 25）与对齐方向。
- **`market_turnover_ratio` 是 0~1 的比例**：画柱要 ×100 且 `.toFixed(4)` 再 `Number()`，否则 `0.07 * 100 = 7.000000000000001` 会让柱高与 tooltip 带浮点尾巴。

## 格式化文案

- **`src/shared/stockFormat.js` 是格式化文案的唯一实现**（`formatChangePercent` / `formatTurnover` / `stockLabel`，三页共用）。新增格式化需求先看这里，不要各页各写一份。
- `formatFlowAmount` 的缺失值统一返回 `null` —— 图表侧据此退化成"只画板块名"，榜单侧用 `?? '—'`。

## 取数节奏

- **页面自己不取数**。`shared/useResource.js` 只在**挂载、`path` 变化、`refresh()`** 三种时机请求一次，**没有任何定时器**。四个页面刷新的唯一入口是工具栏那颗 `shared/RefreshStamp.jsx` —— 它是 `<button className="updated-at">`（悬停手型由 `.updated-at { cursor: pointer }` + hover 边框/文字加深提供），点击调用页面 hook 返回的 `refresh`；`onRefresh` 一路透传：`StockMovesPage`/`SectorMomentumPage`/`HundredDayPage` 直传，资金流页是 `KaipanlaPage → SectorFlowView → FlowControls → RefreshStamp`（**这一条最容易漏接**，四页测试各有一条 `re-requests ... when「更新于」is clicked` 守它）。**手动刷新失败会显示错误态**，不静默保留旧数据 —— 别"顺手"把静默分支加回来。
- 后端 `core/services/calendar.py::is_trading_session` 仍在（管 `fetch_kaipanla_sector_fund_flow` 在非交易时段直接跳过），但它**不与任何前端口径对齐**：前端完全不判交易时段。
- **`RefreshStamp` 只在拿到数据时刻（`updatedAt`）时渲染**（加载中 / 请求失败 / 该日期没有数据时为 `null` → 返回 `null`）：所以这些状态下页面上没有刷新按钮，用户靠日期控件或浏览器刷新重来。要改这个行为，先改 hook 何时置 `updatedAt`。
- **「更新于」的时刻是"库里的数据时刻"**：`RefreshStamp` 的 prop 是 `updatedAt`，值来自响应信封的 `data_updated_at`（由 `useResource` 从 `envelope.data_updated_at` 原样透传，**绝不能用 `Date.now()` / `generated_at` 顶替**）。含义：这份数据写进数据库的时刻 —— 结果行落库后一直躺在库里，页面随时打开，两者可以差几小时；用户想知道的是"屏幕上的数字有多新"。信封没有这个时刻时（首次加载中、请求失败、以及该日期确实没有数据的空态）**胶囊整个不渲染**，所以要拿一个刷新入口时别指望空态里有它。入参是 ISO 串，`formatUpdatedAt` 用 `new Date(value).getHours()` 按浏览器本地时区渲染。
- 「更新于 HH:MM」的时刻文本必须保持在同一元素的**直接文本子节点**里（`更新于 {time}`），测试用整句正则匹配它；把时刻包进 `<span>` 会让 `getByText(/更新于 14:35/)` 静默失效。

## 代码分层（共享层边界）

- 共享层两处：`src/shared/ui/`（通用组件）与 `src/shared/charts/`（`chartBaseline.js` 四图共用基线 + `chartTheme.js` 两个盘后模块构造器；两者都不 import echarts，测试只 mock `init`）。设计令牌在 `src/styles/tokens.css`。
- **单模块专用件不下沉到共享层**：资金流的 `flowOption.js` / `SegmentedControl.jsx` 留在 `features/sector-flow/`。下沉判据是**被两个以上模块消费**。
- 后端对应的公共请求助手是 `core/api/handlers.py`（`require_authenticated` / `optional_date` / `success`），三个盘后模块与 kaipanla 共用；模块自己的视图只声明主张（`core/api/read_endpoints.py` 的 `build_read_endpoints` + `UnavailableRule`）。
- **`src/test/` 是共享测试助手的家**（同目录另有各页面自己的 `*.test.jsx`，别混淆）：
  - `datePicker.js`：`pickDate(target)`（按月份标题导航）。
  - `envelope.js`：`envelope(data, overrides)` 与 `DATA_UPDATED_AT`（5 个页面测试共用，不要再各抄一份）。
  - `refreshStamp.jsx`：`expectRefreshRefetches(Page, { payload, endpoint })`，四个页面共用那条「点「更新于」→ 同 URL 二次请求」不变量。**注意后缀是 `.jsx`** —— 内含 JSX，放进 `.js` 会在 vitest 转换阶段报错。`endpoint` 由调用方给字面量（资金流页用路径构造函数给出），**不要在助手内部用生产代码推导期望值**，否则构造函数自己写错也照样全绿。

## 板块资金流页结构

- `src/features/sector-flow/SectorFlowView.jsx` 是共享视图（只按请求钩子参数化，**不接收 `title`，也不接收 `errorMessage`** —— 后者四个调用点全传同一句话，已落成模块级常量），改资金流交互只需改这一处。
- `.module-stack` 内顺序 = `FlowControls` → `.flow-chart`（独占一行）→ `.flow-rankings`（双榜单，宽屏并排 2 列、`≤64rem` 堆叠 1 列）。`.group-grid` 宽屏两列 2×2；`.chart-frame` 不自带边框。
- 筛选条件（`FlowControls`）直接返回 `<div className="toolbar">`，**不额外包 `.panel`** —— 四个模块的工具栏都直接落在卡片内，多包一层就会多出一个带 border + box-shadow 的小盒。
- 双榜单 `RankingList` 每侧**最多渲染 10 行**（`MAX_RANKING_COUNT`），默认勾选前 5（`DEFAULT_TOP_COUNT`）；API 请求仍是 `inflow_top=25&outflow_top=25`（后端上限 30，`AC-FLOW-002`），展示上限只在前端截断。
- **默认勾选按"每一次取数结果"重算**：闸门是**信封对象本身**（`selectionSourceEnvelope` ref），不是 `business_date`。用业务日期当闸门 ⇒ 同一天内点「更新于 HH:MM」刷新时保留旧勾选，旧勾选的板块一旦掉出新榜单，两个榜单勾选框会全部空着、折线图一条线都不画。改用信封对象后刷新 / 切日期 / 切窗口三条路一条规则全覆盖，且天然挡住中间态（`days` 变了、信封还是上一份时不重算）。代价：手动勾选会被下一次取数刷掉，这是**用户明确选择的行为**（AC-FLOW-009）。
- `SectorFlowView` **没有任何早退分支**：`FlowControls` 恒定渲染，`resolveStateName()` 返回非 null 时只把图表 + 两张榜单替换成对应 `DataState`（loading/error/preparing/empty）。因此"无数据"不再是整页替换，用户改错日期或窗口后控件仍在原位可改回。**新增数据状态沿用此结构，不要退回 early return。**
- 一级导航图标在 `shared/ui/Icon.jsx` 的 `PATHS`；`flow`（板块资金流）是上下两枚反向箭头，关于 (12,12) 中心对称。

## 大涨跌幅看板（`stock-moves` 胶囊几何）

- 胶囊等宽的前提是**两个半区的内容盒完全一样**：`.move-row` 不留 `column-gap`，间距全由 `.move-half { padding-inline: 0.5rem }` 撑开。只给一侧留边距（或把竖线做成会占位的 `border-left` 之外的差异）会让两半内容盒不等宽，胶囊立刻不等宽。行标签槽 `3.25rem` 是"北交所"（3 × 0.875rem = 42px）的下限。
- 宽度预算（用真实片段 + 内联 `tokens.css`/`index.css` 免构建跑无头 Chrome DOM 探针实测）：最长一条 `昀冢科技(+18.68%, 11.26亿)` 文字 **165.36px** → 不压边框需轨道 ≥172.4px（文字 + 左内边距 6px + 边框 1px）、留出完整右内边距需 ≥178.4px。轨道宽 = `(min(窗口, 82rem 容器上限) − 90px 页面与面板内边距 − 116px 轨道骨架) / 6`，胶囊轨道**上限只有 184px**（`.app__main` 是 `min(100%, 82rem)`）。所以任何"再加宽一点"的想法都要先算这条预算，**别再凭估数改断点**。
- 三列断点定在 **`≤80rem` 退 2 列、`≤40rem` 退 1 列**：76rem 会让 1220px 视口右括号越界 3.4px、1250px 仅余 1.6px；80rem 起（1281px）最紧余量 8.4px。**改这个数字必须同时改规格 §3.1.3 与 `AC-MOVE-011`。**
- `.move-pill` 的 `flex-wrap: wrap` 是极端条目（长名称 + 三位数成交额）的兜底，正常数据不触发；`min-width: 0` 不能删（否则网格项被 nowrap 的 min-content 撑开，比轨道还宽）。

## 百日新高新低页明细排序

- `sortByChange(stocks, direction)` 由 `IndustryRanking` 的 `stockSort` prop 驱动：**新高降序、新低升序**（用户明确要求"跌得多的排前面"）；`change_percent` 为 `null` **永远垫底**，同值按代码升序。
