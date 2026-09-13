# A 股复盘项目 · 过度设计与代码复杂度专项审查

- **评审日期**：2026-09-13
- **评审范围**：`backend/`（176 个非迁移、非测试 Python 文件；4 个业务模块共 5531 行）+ `frontend/src/`（41 个生产文件，2871 行）
- **评审方式**：**只读**。未修改任何代码或配置，未执行 `test` / `migrate` / `npm` / `vite` 等命令。本报告是本次唯一的产物。
- **边界说明**：本报告**只审「过度设计」与「复杂度/可读性」**。`docs/reviews/code-review-2026-09-12.md` 已覆盖的正确性、安全、契约、静默失败类缺陷（文件锁回收、错误码闭环、静默丢行等）**不在本次范围**，已修掉的项也不重复提。

---

## 0. 判据（先给标准，避免主观）

一个抽象算不算"过度"，用三条**可判定**的问句：

1. **变体数 ≥ 2 且语义相同** → 抽出来是收益；
2. **只有 1 个生产调用方** → 抽象是负债：读者要多跨一个文件、多做一次跳转才能拼出真实行为；
3. **它防御的场景在生产调用点上不可能发生** → 是负债。

"重复"不用感觉判断，用逐字相同行占比（本报告用 `difflib.SequenceMatcher` 实测，分母取较短文件）。

---

## 1. 总体结论

**问题不是"抽象太多"，而是"同一份设计被手工实现了 3~4 遍"。**

- **后端**：4 个业务模块 5531 行中，约 **1100 行**是三个盘后模块之间的逐字复制。实测重复率：`read_path` 67~74%、`views` 87%、`source_versions` 94%、`writer` 57%。
- **前端**：41 个生产文件 / 2871 行，无状态库、无 wrapper 套 wrapper、无 `useXxx` 套 `useXxx`，**复杂度没有失控**。超标点集中在"三个 hook 几乎相同"与"四个页面外壳复制粘贴"。
- **真正的"过度设计"只有 8 处**，且多数是小件：只有 1 个调用方的参数化、零消费的 props、防御不存在场景的指纹层、按"是否注入 client"隐式切换取值来源的构造器。
- **一个重要的正向观察**：这套代码的注释质量明显高于平均水准，多数"看起来可疑"的地方都写了理由。凡理由成立的，本报告在 §4 明确判定为"不算问题"，不做为了凑数的指控。

---

## 2. 过度设计（OD-1 ~ OD-8）

### OD-1（中）零消费 / 恒取默认值的 6 个 props

| 位置 | 事实 |
|---|---|
| `frontend/src/shared/ui/Panel.jsx:16` `className` | 全仓 **0 处**传入 |
| `frontend/src/shared/ui/Panel.jsx:15` `headingLevel` | 4 处调用**全部显式传 `2`**，等于默认值（`SectorMomentumPage.jsx:35`、`HundredDayPage.jsx:66,73,172`） |
| `frontend/src/shared/ui/Icon.jsx:44` `strokeWidth` | 全仓 **0 处**传入 |
| `frontend/src/shared/ui/Icon.jsx:45` `stroke` | 只有 2 处传入，值都是 `currentColor`，即默认值（`App.jsx:22`、`LoginPage.jsx:29`） |
| `frontend/src/shared/ui/StatRow.jsx:2` `className` | 全仓 **0 处**传入 |
| `frontend/src/shared/ui/TabBar.jsx:25` `variant` | 只有 1 个调用方且恒传 `primary`（`App.jsx:105`）；文件自己的注释（`:8-12`）承认 `tabs--segmented` 样式已删除，传别的值只会得到**无样式的裸 tablist** —— 这是一个**已知无效的旋钮** |

**佐证**：`Panel.jsx:7-9` 显示团队在 2026-09-12 已经清理过一批同类 props（`actions` / `flush`），这一批是漏网的。

**更简单方案**：删掉这 6 个 prop，并清掉调用处 4 处 `headingLevel={2}`、1 处 `variant="primary"`、2 处 `stroke="currentColor"` 的冗余传参。**零语义变化**。

---

### OD-2（中）`usePolledResource` 的"内容指纹"层在防御一个不会发生的场景

`frontend/src/shared/usePolledResource.js:19-31`（`normalizeEnvelopeCodes` + `envelopeCodesKey`）、`:49-56`（`useMemo` + `eslint-disable-next-line`）。

- 注释（`:27-28`、`:52-53`）给的理是：调用方可能传**内联数组字面量**，每次渲染引用都变，会让 effect 重跑并形成请求风暴。
- **实测：四个生产调用方全部传模块级常量** —— `useHundredDay.js:30`、`useSectorMomentum.js:26`、`useStockMoves.js:26`、`useKaipanlaData.js:41`。前提不成立。
- 代价是真实的：为绕开 lint 规则挂了一条 `eslint-disable`，读者要额外追一层指纹函数才能确认 effect 何时重跑。

**更简单方案**：删掉指纹函数与 `eslint-disable`，把 `envelopeErrorCodes` 直接列进依赖数组（约 −12 行）。
**若确实想保留这层防御**：应在调用点强制"必须是常量"（例如导出一个冻结的常量数组），而不是在 hook 里加指纹层 —— 前者把约束写在契约上，后者把成本摊给所有读者。

---

### OD-3（中）三个 hook + 三份常量 + 三份逐字注释，做的是同一件事

`features/hundred-day/useHundredDay.js`(32 行) / `features/sector-momentum/useSectorMomentum.js`(28 行) / `features/stock-moves/useStockMoves.js`(28 行)：除端点路径、错误码清单、常量名以外**逐字相同**，连那段 5 行注释（"盘中每 30 分钟自动重取…"）都复制了 3 份；`30 * 60 * 1000` 常量也定义了 3 次。

**更简单方案**：一个 `useDateResource({ apiClient, date, basePath, pollIntervalMs, envelopeErrorCodes })`，三个文件各剩约 6 行"声明端点与错误码"。`useKaipanlaData` 因多一个 `days` 语义确实不同（`:19-33` 还构造了查询串与两个端点），**可以继续单独存在**，不算问题。

---

### OD-4（中）板块资金流的"网页触发的远程修复"链路

`backend/kaipanla/services/read_path.py` 内：`RepairOutcome`（`:70-81`）、`_repair_snapshot_time`（`:117-128`）、`_repair_current_snapshot`（`:131-262`，132 行）、`_repair_discard_reason`（`:280-295`）。

- 一个 **GET 请求可能发起上游抓取**，行为由 **4 个 `.env` 旋钮**共同决定：`REMOTE_REPAIR_ENABLED` / `REMOTE_REPAIR_TARGET_SECONDS` / `REMOTE_REPAIR_HARD_TIMEOUT_SECONDS` / `REMOTE_REPAIR_MAX_ROWS`；`_positive_setting` 在 4 处分别做校验（`:139`、`:140`、`:372`、`:390`）。
- 实际上这是一次**单页、0 重试**的抓取（`:173-175` 写死 `max_pages=1, max_retries=0`）。
- 命名已经暴露了建模过早：`REMOTE_REPAIR_TARGET_SECONDS` 只是重试提示秒数，与"预算"无关，却和三个真预算并列命名；`_can_attempt_repair` 的 docstring（`:105-108`）自己承认"它是个开关，不是预算，名字曾叫 `MAX_ATTEMPTS`，调大无效"。

**更简单方案（不改行为）**：把 `HARD_TIMEOUT` / `MAX_ROWS` 收敛为常量或在采集层复用 `KAIPANLA_TIMEOUT_SECONDS`，只保留 `ENABLED` 与 `TARGET_SECONDS` 两个可运维旋钮；`_positive_setting` 复用 `backend/env.py` 的 `get_int_setting`，省掉一份重复的解析+校验。
⚠️ **这是产品决策**（要不要保留可运维性），不是纯洁癖 —— 若决定保留 4 个旋钮，至少应把命名对齐语义（`TARGET_SECONDS` → `RETRY_AFTER_SECONDS`）。

---

### OD-5（中）fetcher 构造器按"是否注入 client"隐式切换 4 个参数的来源

`backend/kaipanla/services/fetcher.py:61-93`：`page_size` / `max_retries` / `retry_delay_seconds` / `max_pages` **各自**都是下面这个三分支：

```python
X if X is not None else (读 .env if client is None else <魔法常量>)
```

- 具体后果：注入 client 时（测试与网页修复路径），`max_pages` 变成硬编码 **100**（`:89`），而 `.env` 里配的是 **20**；`retry_delay_seconds` 变成 **0**（`:83`）。
- 也就是说，**同一份代码的行为取决于"是否传了 client"**，而这层耦合完全藏在构造器里，调用点看不出来。
- `__init__` 有 6 个可选参数、4 个用于覆盖配置，正是"为可测试性加的可配置性"扩到生产路径上的典型痕迹。

**更简单方案**：让 `settings` 成为唯一真源（`Fetcher(settings=..., max_pages=..., max_retries=...)`），需要覆盖的调用点显式传关键字；默认值集中在 `flow_client_settings()` 一处，不再有"魔法 100"。

---

### OD-6（低）`SectorFlowView` 的三层间接与"为复用而参数化"

- `features/kaipanla/KaipanlaPage.jsx:21-32` 是 12 行**纯转发**（把 8 个 props 原样递下去），本身不含任何逻辑。
- `features/sector-flow/SectorFlowView.jsx:53-62` 用 8 个 props 描述"一个页面"，注释（`:49`）自称"供资金流类页面复用"，但**生产调用方只有 `KaipanlaPage` 一个**。
- 其中 `errorMessage`（`:60`、用于 `:142`）的唯一生产实参就是 `KaipanlaPage.jsx:29` 里写的字面量。
- **需要说明（不算问题的部分）**：`SectorFlowView.test.jsx:48,64,109` 三处以 props 直接渲染该组件，这是"必须能独立渲染"的正当理由 —— **hook 与 path 参数化是合理的**。
- **但** `errorMessage` 仍然应该落成视图内的常量：测试改为断言该常量即可，没有任何损失。

**更简单方案**：`errorMessage` 移入视图常量；其余 7 个 props 保留（它们是页面状态，不是配置项）。

---

### OD-7（低）0 引用，与"同一概念多套写法"

1. **死代码**：`backend/sector_momentum/services/analysis.py:10` 的 `_METRICS = (ABOVE_5PCT, TOP_5_PERCENT)` 定义后全仓无引用（真正的用法是 `:146-153` 直接写字面量键）。
2. **同一文件内三套"上游失败"映射**（`kaipanla/services/read_path.py`）：`_FETCH_FAILURE_CODES`（`:86-89`，按 `failure_kind` 字符串）、`upstream_code_for_exception`（`:265-277`，按异常类型）、`_PENDING_REPAIR_CODES`（`:46-50`，按 `ErrorCode`）。三者表达同一件事，散在 3 个位置 —— 不是 bug，但读者必须同时记住三张表才能回答"限流最后会得到什么"。
3. **一行包装被定义了 4 次**：`new_source_batch_id()` 在 `stock_moves/services/writer.py:20`、`sector_momentum/services/writer.py:24`、`hundred_day/services/writer.py:26`、`kaipanla/services/writer.py:23` 各写一遍，内容都是 `uuid4().hex`；而 `core/services/sync_daily_prices.py:382` 直接写 `uuid4().hex` —— **同一件事两种写法**。

**更简单方案**：删 `_METRICS`；三张映射表合并为"异常类 → 错误码"的单一注册表（见 §4 第 9 条）；`new_source_batch_id()` 统一走一个来源或干脆全部内联。

---

### OD-8（低）`.env` 解析的 5 秒 TTL 指纹缓存

`backend/backend/env.py:16-62`：为"一个管理命令会问近 200 次配置"引入 `(mtime_ns, size)` 指纹 + TTL 双重缓存，`_file_values` 里有两个"复用已解析结果"的提前返回分支。

- 收益真实但很小（省掉 200 次小文件读取）；代价是 `get_setting` 的语义从"读配置"变成"可能读到最多 5 秒前的配置"（注释 `:14-15` 自己承认"改 .env 生效有 ≤TTL 延迟"）。配置读取是最不该有隐蔽时效性的地方。
- **更简单方案**：进程内首次读取后缓存，只由显式 `reload()` 刷新；或干脆不缓存（本地 SSD 上 200 次 `stat` + `read` 不构成瓶颈），用可预测性换掉这段复杂度。
- 优先级最低，属偏好问题，列出仅为完整。

---

## 3. 复杂 / 不易读（CP-1 ~ CP-7）

### CP-1（高）三个盘后模块的 `read_path` 是同一份文件抄了三遍

**实测（`difflib`）**：

| 对比 | 逐字相同 / 短者 | 占比 |
|---|---|---|
| `hundred_day/services/read_path.py`(339) ↔ `stock_moves/services/read_path.py`(340) | 228 / 339 | **67%** |
| `hundred_day/services/read_path.py`(339) ↔ `sector_momentum/services/read_path.py`(318) | 235 / 318 | **74%**（剔除空行与 import 后 187 / 265 = 71%） |
| `stock_moves/views.py`(74) ↔ `sector_momentum/views.py`(71) | 64 / 71 | **87%** |
| `stock_moves/views.py`(74) ↔ `hundred_day/views.py`(89) | 64 / 89 | **86%**（剔除空行/import 后 41 / 47 = 87%） |
| `hundred_day/services/source_versions.py`(25) ↔ `sector_momentum/services/source_versions.py`(25) | 24 / 25 | **94%** |
| `hundred_day/services/writer.py`(137) ↔ `sector_momentum/services/writer.py`(120) | 68 / 120 | **57%** |

**逐字相同的骨架**（以 `hundred_day` ↔ `stock_moves` 为例）：

- `_latest_local_result()` / `_latest_*_version()` / `_current_source_versions()` / `_result_for_date()`（stale 判定逻辑一字不差）
- `_resolve_read_date()`（连 **docstring 都逐字相同**）
- `read_<module>()`（带 3 分支日志的 36 行外壳）
- `_read_<module>()`（含 `requested_explicitly` 语义、`_local_generate` 回退、`dataset_busy_error()` 的 ~60 行；内部那条 `read_busy` 注释也逐字相同）
- `_data_version()` / `_warnings()` / `read_dates()`（含两处 `try: cache.set(...) except CachePayloadTooLarge: pass`）
- 四个模块各自的 `views.py`：`_require_authenticated` / `_optional_date` / `_success` / `_handle` / `results` / `dates` 结构相同，只有 3 个中文字符串不同

**更简单方案**：在 `core/services/` 放一个 read-path 模板。模板接收 4 个注入点：`MODULE_ID` / `DATASET_KEY`、`latest_local_result()`、`generate(business_date)`、`serialize(result)`（各模块差异确实只在这 4 处）。

- **不违反隔离约束**：`backend/tests/test_module_isolation.py:81-86` 只禁止 **业务模块 → 业务模块** 的 import；`core` 是公共层，四个模块本来就在 import `core.services.*`。同理，`source_versions.py` 的 94% 重复没有任何技术必要性。
- **收益**：每个模块从约 330 行降到约 120 行，合计 **少约 600 行**；更重要的是 **"四个模块读路径行为一致"这条不变式从"靠人记住"变成"结构上不可能不一致"** —— 现存的两段逐字复制注释正是这条不变式在用注释手动维护的证据。

⚠️ **必须在同一次改动里处理的事项**（否则会丢信息）：

1. 三个模块的事件名与字段已被测试断言（`test_fallback.py` 等），模板必须**先复刻现有事件名**再合并；
2. 模块专属理由要逐条迁到注入点，不能丢：`hundred_day` 的 `insufficient_history` 独立事件（`read_path.py:199-205` 的 docstring）、`stock_moves` 的行业版本双依赖说明（`stock_moves/read_path.py:60-66`）、`sector_momentum` 的差异实现；
3. 建议**先在 `sector_momentum` 单独试点一轮**（它是三个里最短、行为最简的），验证测试全绿后再推另外两个。

---

### CP-2（高）四个前端页面的外壳是复制粘贴

| 复制内容 | 出现位置 |
|---|---|
| 同一段 6 行注释（"工具栏在所有数据状态下都保留…"）**逐字 3 份** | `HundredDayPage.jsx:150-155`、`SectorMomentumPage.jsx:118-123`、`StockMovesPage.jsx:39-44` |
| `toggleExpanded`（Set 增删 8 行）**逐字 2 份** | `HundredDayPage.jsx:128-135`、`SectorMomentumPage.jsx:95-102` |
| `<li class="rank-item">` + `rank-item__head` + `detail-toggle` 按钮 + `stock-detail` 展开区（约 20~30 行） | `HundredDayPage.jsx:80-106`、`SectorMomentumPage.jsx:48-81` |
| 同样的 Set 增删（第三次） | `SectorFlowView.jsx:96-103` |
| 工具栏骨架 `DatePicker` + `RefreshStamp` **4 份** | `SectorFlowView.jsx:131-137`、`HundredDayPage.jsx:156-166`、`SectorMomentumPage.jsx:124-132`、`StockMovesPage.jsx:45-60` |
| `stateName === 'error' ? ERROR_MESSAGE : undefined` **4 份** | 上列四页 |
| 9 个相同的 `import`（DataState / resolveDataStateName / resolveDisplayDate / DatePicker / Panel / …） | 四页各自重复 |
| 魔法串 key `` `${countKey}:${item.industry_code}` `` | `HundredDayPage.jsx:76`、`SectorMomentumPage.jsx:45` |

**更简单方案（约 −120 行，风险低）**：

1. `<ModulePage toolbar={...}>{content}</ModulePage>` 承载 `DataState` + `Panel` + `module-stack` + `toolbar` 四层固定骨架（消掉 4 份工具栏与 3 份注释，注释只留一份）；
2. `useExpandedSet()` 承载 Set 增删（消掉 3 份实现）；
3. `<RankItem>` 承载展开卡片（消掉 2 份 20~30 行 JSX，并把 key 的构造收进组件内部）。

行为不变，验证方式就是四个 `.test.jsx` 断言不动而全绿。

---

### CP-3（中）`fetcher.py` 用 `__import__('time').sleep` 绕开自己的导入

`backend/kaipanla/services/fetcher.py`：`:6` 已经 `from time import sleep`，`:91` 却写

```python
self.sleep = sleep or __import__('time').sleep
```

原因是 `__init__` 的参数也叫 `sleep`，遮蔽了导入名。读者必须先意识到"这里的 `sleep` 是那个参数"，才能确认 `__import__` 不是笔误或临时 hack。

**更简单方案**：`import time` 并把参数改名为 `sleep_fn` —— 同项目 `KaipanlaSectorFundFlowClient.__init__`（`kaipanla/services/client.py:106-109`）用的就是 `sleep_fn`。同一模块内两种命名本身就是不一致。

---

### CP-4（中）`_incomplete(...)` 的 6 个位置参数

`kaipanla/services/fetcher.py:107-110`、`:114`、`:118-119`、`:134-144` 等 **8 处**调用形如：

```python
return self._incomplete(0, 0, (0,), None, None, 'The first page failed.')
```

开头连续两个 `0`、随后两个 `None`，读者必须回看定义（`:312-337`）才知道第 4、5 个 `None` 分别是 `source_timestamp` 与 `source_trade_date`。

**更简单方案**：删掉 helper，在调用点用**关键字参数**直接构造 `KaipanlaSectorFundFlowFetchResult`（11 个字段用关键字反而更短更好读）；或把前 5 个字段收敛成一个"本次采集快照元信息"的小 dataclass。

---

### CP-5（中）同名不同义的 `formatRatioPercent`，以及两份 `formatAmount`

- **同名相反语义**：`frontend/src/shared/charts/chartTheme.js:190` 与 `frontend/src/shared/stockFormat.js:30` 都导出 `formatRatioPercent`，但**图表版做 `Math.abs()`，共享版不做**。
- 共享版的注释（`stockFormat.js:6-7`）明确写着"**全站的两位小数、百分号、单位换算只能有这一份实现**" —— 与事实不符，第二份已经存在。
- **第二对**：`chartTheme.js:123 formatFlowAmount` 与 `features/sector-flow/RankingList.jsx:30 formatAmount` 都是"正号 + 一位小数 + 亿"，只差缺失值返回 `''` 还是 `'—'`；`chartTheme.js:122` 的注释还自称"与榜单一致"。
- **风险**：以后调整"占比显示精度"，只改一处就能让图表与页面对不上，且**没有测试会变红**。

**更简单方案**：图表侧复用 `stockFormat`；确需保留两种语义就**改名区分**（如 `formatRatioPercentAbs`），并补一条"同一输入在图表与页面产出同一字符串"的断言。

---

### CP-6（中）`DatePicker` 339 行单组件

`frontend/src/shared/ui/DatePicker.jsx`：一个文件同时承载日期解析、月历生成、弹层定位（`:94-116`）、键盘导航、焦点陷阱（`:219-240`）、漫游 tabindex。

- 用 §0 第 1 条判据：**弹层定位与焦点陷阱不是日期控件特有的**（任何弹出层都需要）→ 变体数 ≥ 2 的候选抽象。
- 纯日期计算已抽到文件顶部（这部分**没问题**）。

**更简单方案**：抽 `usePopoverPlacement(triggerRef, { width, estimatedHeight })` 与 `useFocusTrap(ref)`，组件本体降到约 120 行。

**明确不算问题**：`:211` 依赖数组里的 `cursor` 看似多余，但跨月时 `focusDay` 会被 clamp（`:153`），`cursor` 是唯一的位移信号，保留是对的。

---

### CP-7（低）魔法数字散落

- **图表高度内联 4 处，且各不相同**：`IntradayChart.jsx:24`(380)、`HistoryChart.jsx:23`(380)、`RatioTrendChart.jsx:26`(340)、`MomentumChart.jsx:19`(360)。未进 `src/styles/tokens.css`，而项目其余设计令牌都在那里（`tokens.test.js` 已在守护该文件）。
- `chartTheme.js` 的 `animationDuration: 320` 重复 3 次（`:178`、`:202`、`:314`）。
- `usePolledResource.js:108` 的探活间隔 `30000` 无名，且它的语义（"多久检查一次是否进入交易时段"）与 `pollIntervalMs` 完全不同，容易在阅读时被当成同一个节奏。

---

## 4. 明确判定"不算问题"（避免误伤，逐条给理由）

1. **四个模块各自的 `models.py` / `analysis.py`**：领域规则确实不同（`stock_moves` 的 BSE 独立分组、`sector_momentum` 的两口径评分、`hundred_day` 的 99 日窗口），**不是重复**。为"统一"而合并它们会破坏 `test_module_isolation.py` 守护的隔离边界，收益远小于代价。
2. **`hundred_day/services/flags.py:42-69` 的单调双端队列**：把 99 日滚动极值从 O(n·99) 降到 O(n)，docstring 完整、输入契约明确（要求升序、无重复）。这是"复杂度换正确性能"，成立。
3. **`core/services/locking.py`（243 行）的陈旧锁回收**：有真实失败模式（SIGKILL 后 `finally` 不执行）与明确的取舍（宁可漏判不误判，避免双写）。注释把三条判定规则与回收的原子性都写清了。这是必要的复杂度。
4. **`core/services/file_cache.py:74-107` 用 `DjangoJSONEncoder` 而非 `default=str`**：理由（命中与未命中在线路上必须完全一致、且拒绝不可表示对象）成立，且把"缓存 payload 当传输数据、不要做算术"的后果也写进了 docstring。
5. **`chartTheme.js:173 END_LABEL_GUTTER = 152`**：有实测推导注释（可用宽度 = 152 − 6）。这类"必须靠实测的常量"写进代码是正确做法。
6. **`chartTheme.js:255-276 MOMENTUM_BARS` 的 `value` / `format` 双职**：分别被 series 与 tooltip 消费，**不是**冗余。
7. **`core/logging.py:299-352 ProgressReporter` 的节流**：几千次上游请求的命令没有它会静默几十分钟，运维无法区分"在跑"与"卡死"。成立。
8. **`core/logging.py:63-91 command_logging_context`**：真的省掉了 6 个参数在 4 层调用栈上的透传，且 `log_command_progress` 在无批次时返回 `False` 静默，设计是自洽的。
9. **`kaipanla/services/read_path.py:265-277` 与 `core/api/errors.py:72-99` 的映射重复**：docstring 说明"`core` 不能 import 业务模块的异常类"，**方向判断正确**，不算缺陷。但把两者合并仍是可行的：由 `core` 定义映射协议、各模块注册自己的异常类 → 既保持依赖方向单向，又消掉这份重复（列为低优先级改进，不是问题）。
10. **`core/module_registry.py:53-71`、`backend/env.py:106-118`**：都是"把静默错误变成启动即失败"（空 `ENABLED_MODULES` 会同时搞掉 `INSTALLED_APPS` 与 URLconf）。复杂度花在正确的地方。

---

## 5. 建议的改动顺序（按 收益/风险 排序）

| 序 | 改动 | 预计净减 | 风险 | 验证方式 |
|---|---|---|---|---|
| 1 | 后端 read-path 模板（CP-1） | 约 −600 行 | **中**（触及 3 个模块读路径） | 先在 `sector_momentum` 试点；现有 4 套模块 API 测试 + `test_fallback.py` 全绿后再推另两个 |
| 2 | 前端 `ModulePage` + `useExpandedSet` + `RankItem`（CP-2） | 约 −120 行 | 低 | 4 个 `.test.jsx` 断言不变而全绿即证明无行为变化 |
| 3 | 删 6 个零消费 props（OD-1） | 约 −20 行 | 极低 | 前端全量测试 |
| 4 | 统一格式化实现（CP-5） | 约 −20 行 | 低 | 补一条"图表与页面同输入同输出"的断言 |
| 5 | 3 个 hook 合 1 + 删指纹层（OD-3 / OD-2） | 约 −50 行 | 低 | 4 页 hook 测试 |
| 6 | 死代码与命名（OD-7 / CP-3 / CP-4） | 约 −30 行 | 极低 | 无需额外验证 |
| 7 | 修复链路旋钮收敛（OD-4）、fetcher 构造器（OD-5） | 0（只降复杂度） | **中**（涉及运维配置语义） | 需产品确认是否保留 4 个可运维开关 —— **2026-09-13 用户拍板：收敛成 2 个、settings 成唯一真源**，已落地（§7.1） |

**统一提醒**：上述 1、2 两项都属"结构性去重"，改变的是**代码形状**而非行为。按本仓库既有约定，改动必须**先让现有测试全绿**，再补"行为不变"的断言 —— 不要以"测试没红"当作等价性证明（参见 `.workbuddy/skills/test-assertion-discipline/SKILL.md`）。

---

## 6. 量化附录

**规模**

- 后端：176 个非迁移、非测试 Python 文件；测试文件 54 个。
- 四个业务模块共 **5531 行**：`kaipanla` 2183 / `hundred_day` 1405 / `stock_moves` 996 / `sector_momentum` 947。
- 前端：41 个生产文件 / **2871 行**；测试 20 个文件。

**最大单文件（本报告判定为"不算问题"）**：`core/services/sync_daily_prices.py` 872 行。

- 理由：三种入口（一年初始化 / 单日同步 / 盘中刷新）共用同一套 `_upsert` / `_split_changed_records` / `_begin_runs` / `_complete_covering_runs`，复用是真实的；8 处 `log_command_progress` 是运维必需；三段入口的差异恰恰是**同一数据集的不同传输方式**，拆开会让"行语义必须一致"更难对齐。属"长但有结构"，不是"长而混乱"。

**复制粘贴实测汇总（`difflib`，分母 = 较短文件）**

| 文件对 | 占比 |
|---|---|
| `read_path.py`（hundred_day ↔ stock_moves） | 67% |
| `read_path.py`（hundred_day ↔ sector_momentum） | 74%（剔空行/import 后 71%） |
| `views.py`（stock_moves ↔ sector_momentum） | 87% |
| `views.py`（stock_moves ↔ hundred_day） | 86%（剔空行/import 后 87%） |
| `source_versions.py`（hundred_day ↔ sector_momentum） | 94% |
| `writer.py`（hundred_day ↔ sector_momentum） | 57% |

---

## 7. 落地状态（2026-09-13 深夜更新，7 步全部完成）

§5 的 7 步已按顺序全部执行完。**第 1–6 步产出 `git diff --stat`：33 files changed, +537 / −1381 → 净减 844 行**
（第 7 步在其上再动 8 个文件，见下表）。

最终验证（全部在第 7 步结束后重跑）：
后端全量 **399 tests / `OK (skipped=1)` / 0 残留锁**（基线 395 → 新增 4 条断言）；
前端 **19 文件 152 tests** 全绿（本次未动前端，跑一遍兜底）；
`manage.py check` → `System check identified no issues`；
第 7 步的新断言逐条做了**变异验证**（5 次人为改坏 → 每次都失败、还原后恢复通过，详见 §7.2）。

| §5 序 | 改动 | 状态 | 落地结果 / 与报告的出入 |
|---|---|---|---|
| 1 | 后端 read-path 模板（CP-1） | ✅ 完成 | 新增 `core/services/read_path.py`(288) + `core/api/read_endpoints.py`(108) + `core/services/industry_snapshot.py`(34)；三个模块 `read_path.py` → 122/130/148 行，`views.py` → 17/17/29 行，`source_versions.py` → 各 13 行纯 re-export |
| 2 | 前端 `ModulePage` + `RankItem` + `useToggleSet`（CP-2） | ✅ 完成 | 三页改用共享外壳；**报告未预见**：板块动量页**刻意不渲染 warnings**，外壳因此保留 `showWarnings` 开关 |
| 3 | 删 6 个零消费 props（OD-1） | ✅ 完成 | 上一轮已完成 |
| 4 | 统一格式化实现（CP-5） | ✅ 完成，**方案修正** | 两个 `formatRatioPercent` **不是"只差 `Math.abs`"** —— 一个收 0~1 比例、一个收已是百分比的数值，**不可互换** → 改为**改名** `formatAbsolutePercent`，不是合并。两处 `formatFlowAmount` 确实可合并（只差缺失值写法） |
| 5 | 3 个 hook 合 1 + 删指纹层（OD-3 / OD-2） | ✅ 完成 | 新增 `core/../shared/useDateResource.js`；`usePolledResource` 删掉指纹层与 `eslint-disable`，代价是 `envelopeErrorCodes` 的契约变成"**必须是模块级常量**"（已写进 JSDoc） |
| 6 | 死代码与命名（OD-7 / CP-3 / CP-4） | ✅ 完成 | 删 `_METRICS`；`sleep` → `sleep_fn`；`_incomplete()` 改全关键字传参（7 个调用点） |
| 7 | 修复链路旋钮收敛（OD-4）、fetcher 构造器（OD-5） | ✅ 完成（用户 2026-09-13 拍板"OD-4 收敛成 2 个、OD-5 让 settings 成为唯一真源"） | 见 §7.1 |

### 7.1 第 7 步落地明细

**OD-4：4 个 `.env` 旋钮 → 2 个真旋钮**

| 旋钮 | 处置 | 依据 |
|---|---|---|
| `REMOTE_REPAIR_ENABLED` | 保留，唯一总开关 | `_can_attempt_repair` 的门 |
| `REMOTE_REPAIR_HARD_TIMEOUT_SECONDS` | 保留，唯一真预算 | `timeout_seconds=min(KAIPANLA_TIMEOUT_SECONDS, 5)`，且 `elapsed > hard_timeout` 即丢弃结果 |
| `REMOTE_REPAIR_TARGET_SECONDS`（旧名） | **改名** `REMOTE_REPAIR_RETRY_AFTER_SECONDS` | 它只被写进 202/503 响应体的 `retry_after_seconds`，不影响抓取时长；旧名读起来像预算 |
| `REMOTE_REPAIR_MAX_ROWS`（旧值 1000） | **从 `.env` 删除**，降级为常量 `read_path.REPAIR_MAX_ROWS` | 单页硬上限 80，`>1000` 判断不可达；`min(page_size, max_rows)` 也是恒等变换，一并去掉 |

同步面：`.env`、`.env.example`、`docs/ops/deployment.md` §2 表、`docs/ops/manage-commands.md` §2 表。
`MAX_PAGE_SIZE = 80` 提到 `client.py` 作为唯一出处，`read_path.REPAIR_MAX_ROWS = MAX_PAGE_SIZE` 由它派生 —— 两者漂移会直接被测试断言抓住。

**OD-5：`settings` 成为唯一真源**

新增 `KaipanlaSectorFundFlowFetchSettings` + `fetch_settings(client_settings=None)`（`fetcher.py`），四个参数全部在同一处取值：
`page_size`/`retry_delay_seconds` 取客户端 settings（客户端把 `page_size` 打进 `st`、把 `request_delay_seconds` 用来 sleep，必须一致），
`max_retries`/`max_pages` 直读 `.env`。构造器改成"显式传就用、否则一律取这份默认"，**注入 `client` 不再改变任何一个默认值**，
写死的 `100` 与 `0.0` 删除；旧的两个 `@staticmethod _non_negative_integer/_positive_integer` 提为模块级函数。

真实 `.env` 实测（注入假 client）：`page_size=80, max_retries=2, retry_delay_seconds=1.0, max_pages=20` ——
改动前是 `AttributeError`（page_size）/ `2` / `0.0` / `100`。

### 7.2 变异验证（证明新断言有牙）

| 变异 | 期望被哪条断言抓住 | 实测 |
|---|---|---|
| `len(rows) > REPAIR_MAX_ROWS` → `>=` | 行数闸门边界：恰好 80 行必须放行 | `AssertionError: ('row_budget_exceeded', None) is not None` ✅ |
| 202 的 `retry_after_seconds` 读成 `..._HARD_TIMEOUT_SECONDS` | 重试提示必须来自改名后的键 | `AssertionError: 5 != 9` ✅ |
| 构造器 `page_size` 写死 80 | 注入 client 时 page_size 必须来自配置 | `AssertionError: 80 != 17` ✅ |
| 构造器 `retry_delay_seconds` 写死 0.0 | 同上 | `AssertionError: 0.0 != 0.25` ✅ |
| 构造器 `max_pages` 写死 100 | 同上（旧行为复现） | `AssertionError: 100 != 7` ✅ |

五次变异全部被抓住，且每次均还原后再跑通过。

**两处"报告需修正"的记录**（供下次审查参考）：

1. CP-5 的定性不够准：报告写的是"同名相反语义，只差 `Math.abs()`"，实测差异还包括**入参单位不同**（比例 vs 百分比数值），
   结论因此从"合并"变成"改名"。**今后报告指出"存在第二份实现"时，应在同节直接列出两侧调用点的入参形态。**
2. CP-2 漏掉了"刻意差异"：三页外壳的 3 份逐字注释确实是复制粘贴，但**动量页不渲染 warnings 是刻意的**。
   §2 判据 3 只用来挑"防御不存在场景"，**没有用于挑"看起来重复、实际刻意不同"的地方** —— 这类要靠跑测试发现，不能只看文本相似度。

---

## 8. 第三轮复查（2026-09-13）：死代码 / 重复 / 难读 + 文件残留

在 §5 的 7 步全部落地**之后**又做了一遍：① 找死代码 / 过度重复 / 不简单易读的代码，**找到就修并测**；② 盘点"改代码或测试留下的文件残留"，**问了再删**。

### 8.1 本轮修了 4 处

| # | 位置 | 改动 | 验证 |
| --- | --- | --- | --- |
| 1 | `backend/core/tests/test_file_cache.py:4` | 删无用 import `from unittest.mock import patch` | 全仓 grep 仅此一处提及；后端 399 测试全绿 |
| 2 | `backend/kaipanla/management/commands/fetch_kaipanla_sector_fund_flow.py:6` | 删无用 import `CommandError`（该命令抛 `ValueError` / `IncompleteKaipanlaSnapshot`） | 该命令被 `test_command.py` 12 次 `call_command` + `test_management_contract.py` 覆盖 |
| 3 | `frontend/src/shared/charts/chartTheme.js` | 导出面 **16 → 5**（11 个零外部消费的 `export` 收回模块内）；`animationDuration: 320` ×3 → `ANIMATION_DURATION_MS`；头部注明导出面 | Node ESM namespace 实测导出面 = 5；全仓 grep 确认代码消费点只有那 5 个 |
| 4 | `frontend/src/shared/usePolledResource.js:92` | 裸 `30000` → `SESSION_CHECK_INTERVAL_MS` | 前端 19 文件 153 测试全绿、eslint 干净 |

新增一条断言（`chartTheme.test.js` 的 `chart entrance animation`）：只断"三个 option 构建器的 `animationDuration` 相同且为正数"，**不断 `320` 字面值**。变异验证：把其中一处改成 `999` → 变红（`expected 2 to be 1`）→ 已还原。

### 8.2 CP-6 / CP-7 的最终处置（§5 未排期，本轮给结论）

- **CP-6 `DatePicker` 339 行 → 明确不动。** 按 §0 判据②：全仓只有这一个弹层（`role="dialog"` / `aria-modal` 仅出现于此），抽 `usePopoverPlacement` / `useFocusTrap` 等于"为 1 个调用方建抽象"。**"文件长"本身不是拆的理由**；纯日期计算已在文件顶部（报告自己也说那部分没问题）。
- **CP-7 三条拆开看，结论不一致**：
  - `animationDuration: 320` ×3 → **修了**（同一个语义，判据①成立）；
  - 4 个图表内联高度 340 / 360 / 380 → **不动**：各自是独立的设计取值、**没有共同语义**，抽共享常量会造出假耦合（同页内的两个图本来就一致，380 / 380）；
  - 探活间隔 `30000` → **修了**（现为 `SESSION_CHECK_INTERVAL_MS`）。
- 顺带：`{ color: CHART.label, fontSize: 11 }` 这类**对象片段**虽重复 6 处，但只抽标量、不抽对象字面量 —— 同一份 option 片段被多处 spread 时，共享可变引用有被 ECharts 就地合并的风险。

### 8.3 死代码扫描的方法结论

- `ast` 扫"模块级定义从未被名字引用"，第一遍 **100 个命中全是误报**（Django 测试类、`ModelAdmin`、`MIDDLEWARE` / `TEMPLATES` / `DATABASE_ROUTERS` / `CSRF_FAILURE_VIEW` 设置、`WSGI_APPLICATION`、URLconf 视图 —— 全靠字符串或框架发现被引用）。排除 `tests/ admin.py settings.py apps.py urls.py checks.py manage.py` 后剩 8 个候选，**逐个核对全部在用** → **后端生产代码无死代码**。
- `eslint --max-warnings=0` 对"导出了但没人 import" **不报警**；且 Vite/vitest 下 import 一个不存在的导出往往只是拿到 `undefined` 而不是构建报错 → "lint 干净"与"测试全绿"**都**不能当"没人用它"的证明，必须全仓 grep + 枚举真实导出面。
- 全后端仅有的 2 个未使用 import 即 8.1 的第 1、2 条。

### 8.4 文件残留：无

- 未跟踪文件只有 **7 个**，全部是 CP-1 / CP-2（§5 前两步）新增的**正经源码**，属"尚未 `git add`"而**不是残留**：`backend/core/api/read_endpoints.py`、`backend/core/services/industry_snapshot.py`、`backend/core/services/read_path.py`、`frontend/src/shared/ui/ModulePage.jsx`、`frontend/src/shared/ui/RankItem.jsx`、`frontend/src/shared/useDateResource.js`、`frontend/src/shared/useToggleSet.js`。
- 全盘扫描无 `*.bak*` / `*.orig` / `*.rej` / `*~` / `*.tmp` / `*.swp`；3 个 `*-preview.html` 已删（git 中为 `D`）；`.workbuddy-ai/` 目录已不存在、`git ls-files .workbuddy-ai` 已空。
- `tests/` 仅剩 `.gitkeep`（本轮自建的 `_eslint.txt` / `_backend.txt` 已删）；`backend/data/locks/` 为 0 个锁；`backend/cache/` 的 4 个模块目录已清空（由命令重建）。

---

*本报告最初为只读审查产物，未修改任何代码或配置；§7 / §8 是事后追加的落地与复查状态记录，可随时删除，不影响仓库。*
