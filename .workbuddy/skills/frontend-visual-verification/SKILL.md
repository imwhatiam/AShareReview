---
name: frontend-visual-verification
description: 免登录验证本仓库前端 UI / 图表改动。当你要确认"图表 option 画出来对不对""控件对齐/间距对不对""改完样式长什么样"，但页面需要登录、或没有可用的后端数据时使用。含三条通道：ECharts SSR SVG（验证图表 option，秒级、确定性）、静态预览构建 + 限时 headless Chrome 截图（验证布局与 CSS）、单页静态快照（真实组件 + 构建产物 CSS + 内联 echarts UMD，一个临时 vitest 文件搞定），以及 16 个坑。触发词：截图验证、视觉验证、看看图表、对齐、间距、UI 改完什么样、preview、headless Chrome。
version: 1.4.0
origin: custom
agent_created: true
display_name: "前端视觉验证"
display_name_en: "Frontend Visual Verification"
---

# 前端视觉验证（免登录）

本仓库的页面走 Django session 认证（`/api/core/session/` 未登录时 `authenticated: false`，业务接口 401），
所以**不要试图登录**。按下面两条通道验证。

## 通道 A：ECharts SSR SVG（优先，验证图表 option）

**秒级、确定性、不需要浏览器**。适合验证"横轴刻度是哪些""线端标签文本""图例有没有""标签会不会重叠"。
`src/shared/charts/chartBaseline.js`、`shared/charts/chartTheme.js` 与 `features/sector-flow/flowOption.js` 都不 import echarts、只产出普通对象，可以直接被 Node 引用。
**资金流的图在 `features/sector-flow/flowOption.js`** —— SSR 脚本从那里 import `flowOption`；
`chartTheme.js` 只剩两个盘后模块的 4 个符号（`momentumOption` / `trendOption` / `scoreAxisMax` / `MOMENTUM_BARS`）。
配色与坐标轴工厂（`CHART` / `categoryAxis`）由 `chartBaseline.js` 导出（两个消费者共用），但**别拿它们自己拼 option** —— 要改图就改对应模块的构造器，`isClockTick` 这类留在 `flowOption.js` 模块内。

```js
// frontend/tests/ssr-check.mjs —— 放 frontend/ 子树内即可（node 向上能找到 frontend/node_modules）
import { readFileSync, writeFileSync } from 'node:fs'
import * as echarts from 'echarts'
import { flowOption } from '../src/features/sector-flow/flowOption.js'

const lines = []
const log = (...p) => lines.push(p.join(' '))

const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 1400, height: 380 })
chart.setOption(flowOption({ timePoints, series, yAxisName: '累计净额（亿）', showSymbol: false, timeAxis: true }))
const svg = chart.renderToSVGString()
// ……把结论 log() 进 lines
writeFileSync('tests/ssr-report.txt', lines.join('\n'))
process.exit(0)          // 必须！见坑 6
```

跑：`cd frontend && mkdir -p tests && /Users/lian/.workbuddy/binaries/node/versions/22.22.2-3/bin/node tests/ssr-check.mjs`，然后 `cat tests/ssr-report.txt`。

从 SVG 里抽取（ECharts 的文本**用 `transform="translate(x y)"` 定位，没有 x/y 属性**）：

```js
[...svg.matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map((m) => m[1])           // 文本
/<text([^>]*)>([^<]*)<\/text>/g  +  /transform="translate\(([-\d.]+)[ ,]([-\d.]+)\)"/  // 文本 + 坐标
```

用坐标算相邻标签的 y 差就能量化"是否重叠"（< 字号即重叠）。`legend` 节点数用 `(svg.match(/legend/g)||[]).length`。

**这个通道能直接回答的问题**：横轴刻度到底是哪些（`/^\d{2}:\d{2}$/` 过滤出刻度，一眼看出有没有 13:05）、线端标签文本与 y 坐标（判断会不会互压）、图例存不存在（`option.legend === undefined`）。

**单个标签的水平对齐看 `text-anchor`，不要只看 `transform` 的 x**：ECharts 把 `textStyle.align`
映射成 SVG 的 `text-anchor`（`center`→`middle`、`right`→`end`、`left`→`start`），
所以"11:30 右对齐、13:00 左对齐"这类**逐标签对齐**在 SSR 里表现为两条文本的 x 仍等于各自刻度，
差别全在 anchor 上（实测：`11:30` anchor=`end`、`13:00` anchor=`start`、其余 `middle`）。
顺带核对 `fill` 与 `font-size` 是否与邻居完全一致 —— 用类目项自带的 `textStyle` 做逐标签样式时，
最怕把共享的字号/颜色吃掉。

## 通道 A2：量文字宽度（判断标签会不会被裁）

canvas 上的文字无法从 DOM 读，但可以用浏览器自己的字体度量算宽度，然后再和 `grid.right − endLabel.distance` 比：

```js
// 预览页里执行（字体要和图表一致：ECharts 未设 fontFamily，默认 600 11px sans-serif）
const ctx = document.createElement('canvas').getContext('2d')
ctx.font = '600 11px sans-serif'
ctx.measureText('宁夏回族自治区 +12.3亿').width   // → 118.9
```

**别凭肉眼估**：靠它才能发现 `END_LABEL_GUTTER` 对「7 个汉字板块名 + 三位数亿级」（≈146px，含 `distance` 6）够不够、标签会不会被画布裁掉 —— 该常量当前是 **152**（在 `frontend/src/features/sector-flow/flowOption.js`）。所以这条结论要连同数值一起看：**数值以代码为准**。

## 通道 B：静态预览 + 限时 headless Chrome（验证布局 / CSS）

只在需要看**真实 CSS 布局**（对齐、间距、边框）时用。分三步：

**1. 造数据。** 用只读 read path 导出真实信封（避免手搓字段名出错）：

```bash
cd backend && /Users/lian/.workbuddy/binaries/python/envs/default/bin/python manage.py shell -c "
import json
from kaipanla.services.read_path import read_intraday
r = read_intraday(None, inflow_top=25, outflow_top=25)
json.dump({'status':'ok','business_date':str(r.business_date),'data_version':r.data_version,
           'stale':bool(r.stale),'source':r.source,'warnings':list(r.warnings),'data':r.data},
          open('../frontend/preview/intraday.json','w'), ensure_ascii=False, default=str)"
```

**2. 建预览入口**（`frontend/preview.html` + `frontend/preview/main.jsx`）。
最省事的写法是**绕过 App**，直接渲染目标视图并喂 mock：

```jsx
createRoot(document.getElementById('root')).render(
  <div className="app"><main className="app__main">
    <SectorFlowView phase="ready" envelope={days === 1 ? daily : history} date="" days={days}
      onDateChange={() => {}} onWindowChange={() => {}} errorMessage="..." />
  </main></div>,
)
```
这样**不用 mock session / modules**，也复现了真实内边距。

**3. 构建成静态站点再截图**（不要让 Chrome 打 vite dev server）：

```js
// frontend/preview/vite.preview.config.js
export default defineConfig({ base: './', plugins: [react()],
  build: { outDir: 'preview-dist', emptyOutDir: true, rollupOptions: { input: 'preview.html' } } })
```
```bash
cd frontend && npx vite build --config preview/vite.preview.config.js
# 起服务必须是后台任务（见坑 1）
python -m http.server 5299 --directory preview-dist     # run_in_background=true
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:5299/preview.html?days=1"
```

截图（**必须限时兜底**，见坑 2）：

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
shoot() { # $1=out $2=w $3=h $4=scale $5=url
  rm -f "$1"
  "$CHROME" --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
    --user-data-dir="$PWD/tests/chrome-cpz" --window-size=$2,$3 --force-device-scale-factor=$4 \
    --virtual-time-budget=8000 --screenshot="$1" "$5" >/dev/null 2>&1 &
  local pid=$!
  for i in $(seq 1 45); do [ -s "$1" ] && break; sleep 1; done
  sleep 2; kill $pid 2>/dev/null; pkill -f "user-data-dir=$PWD/tests/chrome-cpz" 2>/dev/null
  ls -la "$1" 2>/dev/null || echo "MISSING $1"
}
shoot tests/v-full.png 1440 1150 1 "http://127.0.0.1:5299/preview.html?days=1"
shoot tests/v-toolbar.png 880 110 3 "http://127.0.0.1:5299/preview.html?days=1"   # 小区域用 3x
```

**量化对齐/间距不要靠肉眼看图**：两把尺子一起用。

① **DOM 探针**（首选，精确到 0.01px）：预览页里 `setTimeout` 后把 `getBoundingClientRect()` + `getComputedStyle()` 塞进一个 `#probe` 节点，用 `--dump-dom` 取回来：

```js
function rect(sel) { const r = document.querySelector(sel)?.getBoundingClientRect()
  return r && { top: +r.top.toFixed(2), bottom: +r.bottom.toFixed(2), height: +r.height.toFixed(2) } }
setTimeout(() => {
  const a = rect('.date-picker__trigger'), b = rect('.segmented')
  document.getElementById('probe').textContent = JSON.stringify({
    a, b, deltaTop: +(b.top - a.top).toFixed(2), deltaBottom: +(b.bottom - a.bottom).toFixed(2),
    style: getComputedStyle(document.querySelector('.segmented')).cssText,
    background: getComputedStyle(document.querySelector('.segmented')).backgroundColor,
  })
}, 1500)
```

据此能直接断言"两个控件上下边缘齐平（delta = 0）"和"外层没有背景/边框（`rgba(0,0,0,0)` / `0px none`）"，**比截图可靠得多**。

**验证"居中对齐"要比中心线，不要比上下边缘**：父容器是 `align-items: center` 时高度不同的子元素边缘必然不等，要比
`center = (top + height / 2)` 的极差。做成一行的子元素，极差应为 0.00px：
个股页 `126.2 / 126.2`、动量与百日页 `131.2 / 131.2`（日期框 37.17px vs 指标卡片 48.39px）。

**验证图标形状（看不到图时的替代办法）**：在预览里加一个 `?page=icons` 分支把图标按 **96px** 渲染（`<Icon size={96} stroke="#000000" />`，外层白底），截图后用 Pillow 扫墨迹：
- 外接框应落在 `[4,20]×[5.5,18.5]/24 × 96` 推算出的范围内（再各加半个描边宽）；
- 连续墨迹"行段"数量能区分笔画结构（注意 `stroke-linecap: round` 的圆帽会让相邻笔画的**行段**相接，行段数不一定等于视觉行数）；
- 把墨迹集合按外接框中心旋转 180° 求重合率：**对称图形 ≈ 85–95%**（差值来自栅格化取整），不对称图形会掉到 ~50%。

② **Pillow 像素扫描**（跨元素、跨行的核对，需 `pip install Pillow` 到托管 venv）：按 `--color-*` 的十六进制值逐行/逐列统计命中像素，取首末行即边缘。例：确认日期框描边在 y=45/y=81、红绿折线像素各 1600+ 命中（顺带排除"截到空白页"）。

**清理**：`rm -rf frontend/preview frontend/preview-dist frontend/preview.html frontend/tests`，并停掉后台服务。

## 通道 C：单页静态快照（真实组件 + 真实 CSS + 真实 ECharts，最省事）

目标是**一个页面**、且不需要交互时，别走通道 B：在 `src/` 下临时写一个 vitest 文件，把真实组件渲染出来取 `container.innerHTML`，再把**构建产物里的 CSS** 和 **`echarts.min.js`（UMD）** 内联进一个 HTML。JSX / 模块解析 / mock 全由 vitest 免费提供，不用写 `vite.preview.config.js`、不用起 http.server。

```jsx
// frontend/src/features/<模块>/__preview.test.jsx —— 用完即删
vi.mock('./MomentumChart', () => ({ default: () => <div className="chart" style={{ height: 360 }} /> }))
const { container } = render(<SectorMomentumPage apiClient={{ request: vi.fn().mockResolvedValue(envelope) }} />)
await screen.findByText('涨幅超过 5%')   // 先等数据态变 ready，再取 innerHTML
writeFileSync('.../preview.html', `<!DOCTYPE html>…<style>${compiledCss()}</style>
<body><div class="app__main">${container.innerHTML}</div>
<script>${echartsUmd}</script><script id="chart-options" type="application/json">${serializeOption(options)}</script>…`)
```

三个关键点：

1. **图表要 mock 掉**：jsdom 没有 canvas，真实 `MomentumChart` 会直接抛错。mock 成 `<div className="chart" style={{height:N}} />`；页面其余结构（panel / toolbar / 榜单 / 展开明细）仍是真实的，所以布局与 CSS 依然可信。浏览器端再对 `.chart` 逐个 `echarts.init(...).setOption(option)`（`querySelectorAll('.chart')` 的顺序 = 页面上图的顺序）。
2. **option 里的函数要活着过去**：`JSON.stringify` 会丢掉 `tooltip.formatter`、`axisLabel.interval` 这类函数。用 replacer 把函数转成 `{__fn: fn.toString()}`，页面里再 `new Function('return (' + __fn + ')')()` 还原（`serializeOption` / `revive`）。不还原的话图能画出来，但悬浮提示是默认样式，容易误判成"formatter 没生效"。
3. **一定要 `option.animation = false`**（见坑 10），并且 CSS 必须取自**刚跑过的** `npx vite build` 产物 `dist/assets/index-*.css`，echarts 取自 `node_modules/echarts/dist/echarts.min.js`。外层套 `<div class="app__main">` 复现真实内边距；用 `file://` 交给 Chrome，不用起服务。
4. **快照 HTML 落盘位置必须忽略**：`writeFileSync` 的目标写成 `frontend/tests/<名字>-preview.html`（`tests/*` 与 `frontend/tests/` 已在 `.gitignore`；`*-preview.html` 也已兜底）。**不要写在仓库根** —— 落到仓库根会被 git 跟踪，2.4MB 一次性产物（单文件 1.19MB / 1.25MB 量级）会进版本库。

## 通道 C2：真实组件片段 + 内联 CSS 量布局（免构建，量胶囊/轨道几何首选）

手上有现成片段（vitest 临时文件 dump 出的 `innerHTML`，或之前留下的 `tests/*.html`）时**不必 `vite build`**：`tokens.css` 是纯令牌、`index.css` 是纯 CSS，把两者**直接内联**进一个临时 HTML（删掉 `@import './styles/tokens.css';` 那一行），外面套
`<div class="app"><main class="app__main"><section class="panel"><div class="panel__body">片段</div></section></main></div>`
就复现了真实的 90px 页面与面板内边距。探针页放 `frontend/tests/` 下（用完删；**别放 `/tmp` 或 `/private/tmp`** —— 项目外一律不动，见 `.workbuddy/memory/MEMORY.md` §0 边界铁律）。

```js
// 量"文字右缘到右边框的余量"，不要只看越界：用户说的"右括号和右边框重合"
// 多数是余量被吃到 0~2px，此时 scrollWidth 仍等于 clientWidth、看起来"没溢出"。
const r = (el) => el.getBoundingClientRect()
const margin = r(pill).right - r(pill.lastElementChild).right   // < 右内边距即贴边，< 0 才越界
```

- **探针内联的是 CSS 快照**：改完 CSS 必须重新生成探针文件，否则量的是旧样式（症状：改完断点后拿到的仍是旧值）。
- 跑法：`--window-size=W,1200 --hide-scrollbars --virtual-time-budget=4000 --dump-dom > out.html`，再用 `re.search(r'<pre id="probe"[^>]*>(.*?)</pre>', out, re.S)` 取回（JSON 带换行，`grep -o` 只能拿到第一行）。
- 替换 `run()` 函数体时别把 `window.addEventListener('load', …)` 一起替换掉 —— 症状是 `<pre>` 空白、像是"探针没跑"。
- **本仓库已定稿的数**（动看板/胶囊宽度前先对账）：最长胶囊文字 **165.36px**；`.app__main` = `min(100%, 82rem)` → 看板宽 = `min(窗口,1312) − 90`，**上限 1222px**；三列轨道 = `(看板 − 116) / 6`，**上限 184px**；不压边框需轨道 ≥172.4px、留出完整右内边距需 ≥178.4px → 三列断点 `80rem`（`≤40rem` 退 1 列）。

## 通道 D：自包含探针页 + 页内 canvas 像素扫描（量"某个标签究竟画在哪、会不会叠字"）

通道 A 的 SSR 文字宽度是**估算**、通道 A2 的 `measureText` 只是**字宽**，都答不了"渲染出来这一段墨迹的左右边界在哪"。
最直接的办法：**让页面自己扫自己那张 canvas** —— 能证明午休两侧的 11:30 / 13:00 各自贴着自己刻度朝外、
量出间隙 26.0 / 20.7 / 17.3 / 14.0px。比截图 + Pillow 快一个数量级，也不受窗口尺寸与缩放影响。

```js
// 页面内：box = 图表容器；rect = chart.getModel().getComponent('grid').coordinateSystem.getRect()
const dpr = window.devicePixelRatio || 1
const img = box.querySelector('canvas').getContext('2d')
  .getImageData(x0 * dpr, y0 * dpr, w * dpr, h * dpr)     // 只取轴标签那一条
// 逐列判断"这一列有没有标签颜色的像素" → 合并连续列（列间距 ≤2 像素算同一段）→ 每段 { from, to }
```

- 扫描带：纵向 `rect.y + rect.height .. +30`，横向 `rect.x - 12 .. rect.x + rect.width + 12`；
  标签色 `#5c6b85` = `rgb(92,107,133)`，容差 ±42 就够（红 `207,44,45` / 绿 `13,143,87` 都进不来）。
- 刻度自身的 x 用 `chart.convertToPixel({ xAxisIndex: 0 }, '11:30')` —— **类目轴传值，不传下标**。
- **段会被冒号处的空隙切成两半**（`11` / `30` 两段）：判"是否同一标签"时要把相邻段合起来看，
  否则会把段间 1.5px 误读成"两个标签重叠"。合并阈值取列间距 > 2 像素才算断开。
- 多宽度一起量：容器宽度是**唯一**影响横向间距的变量（`grid.width / (n-1)`），
  一次跑 1440 / 1188 / 1024 / 860 四档就足以断言"任何宽度都不叠"。

**页面怎么拿到"真实的 option"**：不要 `JSON.stringify(option)` 把函数传过去 —— `flowOption.js` 是 ESM，
模块内的 `isClockTick` 这类闭包**过不了河**（`new Function` 里找不到它们，且报错要等到 ECharts 调
`getViewLabels` 时才炸，看起来像图表库的 bug）。正确做法是把整个模块打成 IIFE 内联，页面里调真正的构建器：

```js
// 生成器里（frontend/node_modules/esbuild）
const bundle = await build({ entryPoints: ['src/features/sector-flow/flowOption.js'], bundle: true,
  format: 'iife', globalName: 'flowChart', write: false })
// 页面里：const option = flowChart.flowOption({ timePoints, series, yAxisName, showSymbol: false, timeAxis: true })
//        option.animation = false          // 见坑 10
```

**探针页必须能自报错误**：脚本一旦在写结果之前抛掉，结果节点就只剩"（等待渲染）"，看起来像"探针没跑"。
`<pre id="probe">` 之外再挂一个 `window.addEventListener('error', function (e) { /* 把 e.message/e.error.stack 写进同一个节点 */ });`，
并给每个用例套 try/catch（一条失败不影响其余）。

一次 Chrome 跑完两件事：`--dump-dom` 与 `--screenshot=$PWD/tests/shot.png` **可以同时给**，
仍然要套"轮询产物 + `pkill -f "user-data-dir=..."` 兜底"。取回结论用
`re.search(r'<pre id="probe">(.*?)</pre>', html, re.S)`（JSON/多行带换行，`grep` 只能拿到第一行）。

## 坑

1. **`(python -m http.server ... &)` 会随命令结束被回收**（和 `(npx vite &)` 同一个坑）。表现：Chrome 拿到 `ERR_CONNECTION_REFUSED`，而且**一直不退出**，挂 6 分钟，极易误判成"Chrome 卡死"。→ 用 `run_in_background=true` 起服务，**先 `curl` 确认 200 再截图**。
2. **Chrome 截完图不退出**（本机疑似 sandbox 拦 `code_sign_clone` / RLZ 写入，首次启动约 2 分钟）。→ 用上面的 `shoot()` 轮询 PNG + `kill $PID` 兜底。
3. **并行起多个 Chrome 实例会被沙箱拒绝**（`code_sign_clone` 写被拒）。→ 串行跑。
4. **不要 `pkill -f "Google Chrome"`** —— 会连用户正在用的浏览器一起杀掉。只 `pkill -f "user-data-dir=$PWD/tests/chrome-cpz"`。
5. **macOS headless Chrome 的 `--window-size` 宽度有最小值（约 485px）**，窄屏要用 `<iframe width="390">` 包一层再截；`sips --cropOffset` 在部分版本不生效，别依赖它做像素测量。
6. **ECharts SSR 脚本跑完不会退出**（动画/定时器让事件循环一直不排空），命令会吊在那直到超时，看起来像"卡死"。→ 脚本末尾 `process.exit(0)`；结论**写文件再读**，别只靠 stdout（接 `| head` 时可能一个字符都看不到）。
7. **macOS 没有 `timeout` 命令**（报 `command not found`，`exit 127`）。限时跑脚本用 `cmd & pid=$!; sleep 20; kill $pid`。
8. **ECharts 6 里 `chart.getZr().storage.getDisplayList()` 取不到文本元素**（返回 0 个 text），想从真实实例反读"渲染后画了哪些字"是行不通的 —— 要渲染后文本走通道 A（SSR），要标签宽度走通道 A2（`measureText`）。
9. **`--window-size` 太小会截出空白 PNG**：`--window-size=96,96` 时得到的是一张 292 字节的纯色图，即使 DOM 已经渲染正确（同一 URL `--dump-dom` 能看到完整节点）。看着像"页面没渲染"，其实是截图通道的问题。→ 画布至少给到 200×200，并把 `--virtual-time-budget` 提到 20000；另外**别用 96px 窗口去截 96px 的图形**，改成在页面里放大渲染再扫像素。
10. **静态快照里的 ECharts 必须关动画**：`momentumOption` / `trendOption` / `flowOption` 都带入场动画（值取自 `chartBaseline.ANIMATION_DURATION_MS`，当前 320），`--screenshot` 可能在首帧（柱高为 0）或动画中途按下快门，截出来像是"图没画"。→ 预览页里在 `setOption` 前写 `option.animation = false`。
11. **看小字别靠原图**：整页 1440×2600 的截图里坐标轴刻度只有几像素，肉眼会误判。用 Pillow 放大目标区域再读：`im.crop((x0,y0,x1,y1)).resize((w*2,h*2), Image.LANCZOS)`（`sips --cropOffset` 不可靠，别用）。靠放大才能发现"最右轴刻度其实落在面板内"，否则会把正常的留白误判成溢出。
12. **别在第一次截图时用 `--virtual-time-budget` 而不加 kill 兜底**：`--virtual-time-budget=8000` 的那次可能挂 5m39s 才被手动停掉（PNG 其实早已写好）。→ 无论用不用 virtual time，都套 `shoot()` 的"轮询 PNG + `pkill -f user-data-dir=...`"模式；`--headless=old` 与 `--headless=new` 都能出图。
13. **内存吃紧时整条命令会被内核杀掉，且毫无输出（最容易误判）**：本机 16GB，用户同时开着浏览器时 swap 会到 ~6.7G/7.2G、空闲内存只剩 ~100–150MB。此时 `npx vitest run` / headless Chrome **直接 SIGKILL（exit 137），连 `echo` 都不执行**，终端只显示"命令凭空失败"，极易被当成代码或脚本 bug。先查 `vm_stat | sed -n '2p'`（Pages free × 16384 = 剩余字节）与 `sysctl vm.swapusage`，再决定：
    - Node 侧加堆上限：`NODE_OPTIONS="--max-old-space-size=1024" npx vitest run`（`vite build` 用 1536）。
    - **别反复重启 Chrome 硬碰**：`--dump-dom` 接管道几乎必被杀；改成 `> tests/dom.html` **重定向到文件**，实测（空闲内存 1.9G）稳定成功，`grep` 到关键字段就 `pkill -f "user-data-dir=..."` 收工。窗口一紧张就退回**先存盘截图、再用 Pillow 逐像素分析 PNG 取几何量**（面板边界、元素宽度、轨道间距都能反算），比反复起浏览器可靠得多。
    - 查进程别用 `ps`（本沙箱 `operation not permitted`），用 `pgrep -fl <pattern>`；注意 `pgrep -c` 在 macOS 上不支持。
14. **生成器里的页面脚本不能用模板字符串**：生成器本身用模板字符串拼 HTML 时，页面脚本里的 `${...}` 会被**外层**先展开（症状：生成器报 `SyntaxError: Unexpected identifier 相邻整半点间距`）。页面脚本一律用 `'a' + b` 拼。
15. **`})\n(function () {` 会被 ASI 粘成一次函数调用**：前一个 IIFE 结尾漏分号，后一个 IIFE 就成了它的调用参数。症状是 `Uncaught TypeError: window.addEventListener(...) is not a function`，**整段脚本一行都没执行**（DOM 里看不到任何节点）。IIFE 之间必须写分号。
16. **page 里 `JSON.stringify` 过的函数会丢闭包**（`ReferenceError: isClockTick is not defined`，报在 `getViewLabels` 里）：见通道 D，改用 esbuild 内联真实模块。

## 真实数据的坑

- 库里经常**只有单点快照**（采集命令每天只跑一次），分时曲线会是"贴 0 后末点跳变"，看起来像 bug 其实是数据。查一下 `SELECT trade_date, COUNT(DISTINCT snapshot_time) FROM ... GROUP BY trade_date` 确认。
- 要验证"多条折线散开"的观感，就按真实板块名与量级**合成**一条完整交易日曲线（仅用于预览，别写进仓库）。
- 多日接口的 `items` 按 `trade_date` **降序**返回，前端 `reverse()` 成升序；mock 若给升序，横轴会变成从新到旧。
