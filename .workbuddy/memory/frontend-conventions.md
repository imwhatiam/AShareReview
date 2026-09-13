# 前端与页面文案约定（专题）

从 `.workbuddy/memory/MEMORY.md` 拆出，按需读取。

## 术语与页面文案

- **行业快照只有一层，没有父子层级（2026-09-12 删除）**：中文术语按场景分两套 —— 导航/模块名/告警说**「板块」**（板块资金流、板块动量、「未映射到开盘啦板块」），分析内容说**「行业」**（新高/新低行业排行、行业动量评分图）。**英文标识符也已正名（2026-09-12）**：契约 `Industry`、`CompleteMarketSnapshot.industries`、API 响应键 **`industries`**（`stock_moves` 与 `hundred_day` 都是）—— 前端读 `item.industries`，不是旧的 `parent_industries`。
- **四个业务页面无页面级标题**：模块名只在左侧导航 Tab 出现（无障碍靠 `<main role="tabpanel" aria-label={display_name}>`）；模块级 `Panel` 写裸 `<Panel>`（`subtitle` prop 已删）；页面内区块标题 `headingLevel` **从 2 起算**（避免与 `App` 的 `<h1>` 跳级）。
- 页面顶部**不再展示「业务日期 / 数据版本」**：`shared/DataMeta.jsx` 只留 `stale` + `warnings`；**`partial` chip 已删**（后端 `status='partial'` 完全等价于 warnings 非空，chip 与紧随其后的告警列表是同一件事）。`DataState` 已删 `businessDate`/`dataVersion`/`partial` 三个 prop，但 `envelope.business_date`/`data_version`/`status` 仍是 API 契约（`SectorFlowView` 靠 `business_date` 做"换日期重置勾选"）。
- 板块动量页**按设计不渲染 warnings**（唯一告警"N 只有效股票未映射到开盘啦板块"用户无法处理且每次都在）：数量仍在 `data.unmapped_stock_count`，`stale` 保留。个股页无独立统计块，总数写在复制按钮文案里（`共 N 只股票，全部复制`，N = `data.distinct_stock_count`）。
- 文案多集中在共享组件（`Panel` title / `SegmentedControl` legend / `DataMeta` chip / 日期控件 aria）—— 改文案先 grep 组件，不只 grep 页面文件，一处改动即全站生效。
- 日期与窗口控件**不渲染可见标签**：日期用 `aria-label="数据日期"`（挂在触发器 button 上），窗口用 `role="group" aria-label="统计窗口"`。5 个页面测试的 `getByLabelText('数据日期')` 就靠这些 aria —— **改这两处务必保留 aria 名**，不要"清理"成无标签控件。
- 前端测试大量用 `getByText` 精确匹配整句（`getNodeText` 只拼元素直接文本子节点）：被断言的整句文案必须保持在同一元素内，不能拆进子元素。

## 日期与工具条

- 日期控件是自绘 `src/shared/ui/DatePicker.jsx`（`DateField.jsx` 已删，4 个页面都用）：**原生 `input[type=date]` 的日历弹层在 UA shadow DOM 内无法改样式，禁止退回原生控件**。弹层 `position: fixed`（祖先 `.panel` 有 `overflow: hidden`，absolute 会被裁）。
- 测试选日期一律用 `src/test/datePicker.js` 的 `pickDate(target)`（内部按月份标题导航；弹层默认停在 value 所在月，**写死月份会随运行日期漂移而挂**，别绕过它直接点格子）；读当前日期用触发器文本断言 `toHaveTextContent`，不是 `toHaveValue`。
- 日期显示值统一走 `shared/businessDate.js` 的 `resolveDisplayDate(selectedDate, envelope)`（= 手选日期 || `envelope.business_date` || ''）。四个页面曾各自实现而漂移（有一轮只有资金流页显示了具体日期），新增页面一律用它。
- 资金流页**所有统计窗口都以最近一个已发布交易日为终点**：`KaipanlaPage.handleWindowChange` 点任一窗口（当日/5/10/20日）都 `setDate('')`，空 date 由后端取最新业务日期；多日窗口 = `trading_day_window(end_date, count=days)` 截止该日往回取 N 个交易日。用户显式选日期时该日期才是窗口终点。
- `.toolbar` 为 `align-items: center`（原 `flex-end`）：日期框 37px 与指标行 22px 高度不同，居中才不会"文字贴底、上方留空"。四个页面的"日期 + 统计/按钮"放在**同一行**；窄屏下 `.toolbar > .stat-grid` 与 `.date-picker` 都 `flex: 1 1 100%`。
- **指标行（`.stat-row`/`.stat-grid`）是纯文字**（无 padding/border/圆角/底色），`--up` 用 `--color-market-up`、`--down` 用 `--color-market-down`，只靠**文字颜色 + 字重 600** 区分；`.stat-grid` 为自然宽度 + `align-items: baseline` + `gap: var(--space-2) var(--space-5)`（等分列宽已删，等分只对"卡片"外观有意义）。仅板块动量页与百日页在用。
- **内容区按钮一律 `.btn`**（白底 + `--color-border-strong` 描边）；实心品牌蓝 `.btn--primary` **只用于登录页提交**。
- `.segmented`（统计窗口分段控件）**无外层背景/边框**；`.segmented__item` 纵向内边距与 `.date-picker__trigger` 同为 `0.4rem`，靠这个在居中对齐下保证上下边缘齐平；激活态用 `--color-brand-50` 浅蓝底（`box-shadow` 已去掉）。

## 令牌与图表

- 外壳用品牌蓝，**红/绿仅表示涨跌**（红涨绿跌），不得用作操作色。`tokens.css` 必须保留互不相同的 `--color-market-up/down/error`；这条约定现在由 `src/styles/tokens.test.js` 按**色相**守（`up` 落在色环两端 ≈0°/360°、`down` 在 90°–170°、`error` 不等于其中任一个），**不再读 CSS 文本断子串**（那只是把令牌抄一遍，两边一起改就照样通过）。该文件只读文件、不碰 DOM，因此首行是 `/* @vitest-environment node */` —— jsdom 下 `import.meta.url` 不是 file URL，`new URL('./tokens.css', import.meta.url)` 会抛 `TypeError: The URL must be of scheme file`；**别改成 CWD 相对路径**绕过，那会把用例绑死在调用目录上。
- **`index.css` 的 `:focus-visible` / `@media (max-width: 40rem)` / `overflow-x: auto` 已没有任何自动化断言**（原先在 `DataState.test.jsx` 里靠读文件断子串，2026-09-13 移除：jsdom 不做层叠也不做命中测试，读文本既过严又过松）。这三处的回归现在只能靠 `frontend-visual-verification` 截图人眼确认，改动它们时别指望测试兜底。
- 图表配色只允许来自 `shared/charts/chartTheme.js`。**2026-09-13 起该文件的导出面刻意收敛为 5 个符号**：`momentumOption` / `trendOption` / `flowOption` / `scoreAxisMax` / `MOMENTUM_BARS`；`CHART` / `TOOLTIP` / `GRID` / `LEGEND` 与各 axis / series 工厂都是**模块内私有**的 —— 要改图表就改这四个 option 构建器，**不要**再 import 调色板自己拼 option（上游已无此导出）。**红/绿严格留给涨跌方向**，衡量"强弱/规模"的图（如动量评分）用品牌蓝（`score` 色）。类目轴刻度由内部 `shortCategoryLabel()` 把 `2026-09-10 15:00` 显示成 `09-10`，但 **`option.xAxis.data` 必须保持原始值**（`flowView.test.jsx` 直接断言）。
- 资金流折线图（`flowOption`）**不渲染顶部图例**：板块名 + 资金净额常驻每条折线右端（`endLabel`，`formatFlowAmount()` 统一「正数带 + / 一位小数 / 亿」）。`grid` 为 `{ top: 36, right: 152 }`：`right` 是线端标签留白，标签画在 grid 右边界之外，**可用宽度 = `right` − `endLabel.distance`(6)，不够就被画布裁掉等于丢掉板块名**（实测最坏 7 个汉字板块名 + 三位数亿级 ≈146px，`flowView.test.jsx` 断言 ≥146；改标签文案/字号必须复查这个留白）；`top` 只需够 y 轴名称（设 20 会把轴名裁掉）。`labelLayout.moveOverlap:'shiftY'` 的最小行距**锁死在字号**（11px），给 `endLabel` 加 padding 无效。
- **分时横轴刻度按「分钟数是 10 的整数倍」判断（`isClockTick` + `clockCategoryAxis`），不要按索引等间隔抽稀**：上午 09:30–11:30 是奇数个槽，按索引跨过午休会错位成 13:05…14:55。该轴必须 `hideOverlap: false`，否则相邻的 11:30 与 13:00 会被防重叠抽稀丢掉。`option.xAxis.data` 永远保留原始 timePoints。

## 板块资金流页结构

- `src/features/sector-flow/SectorFlowView.jsx` 是共享视图（按请求钩子 / 错误提示参数化，**不再接收 `title`**），改资金流交互只需改这一处。
- `.module-stack` 内顺序 = `FlowControls` → `.flow-chart`（独占一行）→ `.flow-rankings`（双榜单，宽屏并排 2 列、`≤64rem` 堆叠 1 列）。旧类名 `.flow-layout` / `__main` / `__side` 与榜单内部滚动（16rem 限高）**已全部删除**。`.group-grid` 宽屏两列 2×2；`.chart-frame` 不自带边框。
- 筛选条件（`FlowControls`）直接返回 `<div className="toolbar">`，**不额外包 `.panel`** —— 四个模块的工具栏都直接落在卡片内，多包一层就会多出一个带 border + box-shadow 的小盒。
- 双榜单 `RankingList` 每侧**最多渲染 10 行**（`MAX_RANKING_COUNT`），默认勾选前 5（`DEFAULT_TOP_COUNT`）；API 请求仍是 `inflow_top=25&outflow_top=25`（后端上限 30，`AC-FLOW-002`），展示上限只在前端截断。
- `SectorFlowView` **没有任何早退分支**：`FlowControls` 恒定渲染，`resolveStateName()` 返回非 null 时只把图表 + 两张榜单替换成对应 `DataState`（loading/error/preparing/empty）。因此"无数据"不再是整页替换，用户改错日期或窗口后控件仍在原位可改回。新增数据状态沿用此结构，不要退回 early return。
- 一级导航图标在 `shared/ui/Icon.jsx` 的 `PATHS`；`flow`（板块资金流）是上下两枚反向箭头，关于 (12,12) 中心对称。

## 大涨跌幅看板（`stock-moves` 胶囊几何，2026-09-12 实测定稿）

- 胶囊等宽的前提是**两个半区的内容盒完全一样**：`.move-row` 不留 `column-gap`，间距全由 `.move-half { padding-inline: 0.5rem }` 撑开。只给一侧留边距（或把竖线做成会占位的 `border-left` 之外的差异）会让两半内容盒不等宽，胶囊立刻不等宽。行标签槽 `3.25rem` 是"北交所"（3 × 0.875rem = 42px）的下限。
- 宽度预算（用真实片段 + 内联 `tokens.css`/`index.css` 免构建跑无头 Chrome DOM 探针实测）：最长一条 `昀冢科技(+18.68%, 11.26亿)` 文字 **165.36px** → 不压边框需轨道 ≥172.4px（文字 + 左内边距 6px + 边框 1px）、留出完整右内边距需 ≥178.4px。轨道宽 = `(min(窗口, 82rem 容器上限) − 90px 页面与面板内边距 − 116px 轨道骨架) / 6`，胶囊轨道**上限只有 184px**（`.app__main` 是 `min(100%, 82rem)`）。所以任何"再加宽一点"的想法都要先算这条预算，别再凭"最长约 171px"之类的估数改断点。
- 三列断点定在 **`≤80rem` 退 2 列、`≤40rem` 退 1 列**：76rem 是按"看板占满视口"误算的，实测 1220px 视口右括号越界 3.4px、1250px 仅余 1.6px；80rem 起（1281px）最紧余量 8.4px。改这个数字必须同时改规格 §3.1.3 与 `AC-MOVE-011`。
- `.move-pill` 的 `flex-wrap: wrap` 是极端条目（长名称 + 三位数成交额）的兜底，正常数据不触发；`min-width: 0` 不能删（否则网格项被 nowrap 的 min-content 撑开，比轨道还宽）。
