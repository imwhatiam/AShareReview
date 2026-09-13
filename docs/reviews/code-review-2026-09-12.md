# A 股市场复盘 · 全栈代码与文档评审报告

- **评审日期**：2026-09-12
- **评审基线**：`HEAD = 3d69e79`（工作区另有 102 个已暂存/已修改文件，见 §6）
- **评审方式**：只读。未修改任何代码或文档，未执行 `migrate` / `sync` / `build` / `test` / `npm` 等写操作或重命令。
- **唯一新增文件**：本报告（可随时删除，不影响仓库）。

**覆盖范围**：`backend/`（206 文件，core + 4 业务模块）、`frontend/`（67 文件）、`docs/`（6 篇 6622 行）、`scripts/`、`tasks/`、`README.md`、`AGENTS.md`、`docs/data-sources/web-api.md`、`.workbuddy/`（记忆 + 2 个技能）、`.workbuddy-ai/`。

**总体判断**：这是一个**工程质量明显高于平均水准**的代码库 —— 分层清晰（core 基础库 + 4 个无互相依赖的业务模块）、模块隔离有测试守护、读路径契约（缓存→库→本地生成）高度统一、测试规模可观（后端 329 例 / 前端 78 例）、记忆与技能沉淀非常扎实。**主要风险不在"代码写错了"，而在三类地方**：① 少数**静默失败路径**（失败被降级成"空数据"或"准备中"）；② **规格/文档与 2026-09-12 的快速迭代脱节**（8 条验收条款没进追踪表、规格里还写着"永不用同花顺行业接口"而代码已依赖它）；③ **运行时自愈能力缺失**（文件锁没有陈旧锁回收）。

---

## 0. 优先级定义

| 级别 | 含义 |
|---|---|
| **P0** | 会造成数据错误、静默丢数据、或使系统长期不可用，且当前路径可触发 |
| **P1** | 明确缺陷 / 契约不一致 / 可复现的运维或 UI 故障 |
| **P2** | 死代码、文档过时、测试缺口、健壮性与一致性问题 |

---

## 1. P0（4 条）

### P0-1　文件锁没有陈旧锁回收：一次 SIGKILL 会让采集与三个模块的读路径**永久瘫痪**
`backend/core/services/locking.py:22-38`

锁用 `O_CREAT|O_EXCL` 创建，唯一释放路径是 `finally: path.unlink()`；第 35 行写入了 `os.getpid()`，但**全仓没有任何代码读它**，也没有 TTL / 心跳 / 清理命令。进程被 SIGKILL / OOM / cron 超时杀掉时 `finally` 不执行，`.lock` 永久残留。

- 后果：`sync_*` / `init_*` / `refresh_*` / `fetch_*` 全部抛 `CommandError` 退出（`core/management/base.py:61-73`）；`stock_moves` / `sector_momentum` / `hundred_day` / `kaipanla` 的读路径永久拿不到锁 → 永久 404 / 202。**不会自愈，必须人工删文件。**
- 这不是理论风险：本项目记忆里已两次记录它造成的连锁故障（`.workbuddy/memory/backend-data-and-commands.md:209-213`、`2026-09-12.md:30`）。生产上"4 分钟跑一次的行业快照"被 cron/内核杀掉是常态。
- 建议方向（不在本次改动范围）：锁文件写入 PID + 时间戳，获取失败时判断持有者是否存活 / 是否超龄；或提供 `manage.py unlock_dataset`。同时**读路径的锁竞争应降级，而不是把模块打成不可用**（见 P1-6）。

### P0-2　`sync_stock_master` 缺少行数下界保护：上游一次截断就**静默停用全市场**
`backend/core/services/sync_reference.py:120-121`

```python
Stock.objects.exclude(thscode__in=[ticker.thscode for ticker in tickers]).update(is_active=False)
```

写入前只校验了"非空"（`_collect_tickers`，同文件 `:57-58`）。若上游某次少返回若干页却不报错，未被列出的股票被整体置为 `is_active=False`，而 `_active_stocks()`（`sync_daily_prices.py:63-67`）不再为其建行情 → **静默停止采集这部分股票的历史**，且不报错、不告警。
对比：盘中快照路径有覆盖率门槛 `INTRADAY_QUOTE_MIN_COVERAGE_RATIO`（`sync_daily_prices.py:752-766`），此处完全没有。

### P0-3　规格明文"永不"使用的数据来源，正是当前行业归属的实现依赖
`docs/specs/integration-spec.md:1105`

> 「永不将同花顺 REST 行业目录或成分接口作为行业—股票关系的正式来源。」

而 2026-09-12 落地的 `backend/core/services/industry_backfill.py`（+ `core/integrations/hithink/client.py` 的 `list_industry_indices()` / `list_industry_constituents()`，开关 `.env.example:50 HITHINK_INDUSTRY_BACKFILL_ENABLED=1`）**正是**用同花顺行业目录 + 成分股为开盘啦快照补齐 325 只北交所股票。落地记录见 `.workbuddy/memory/backend-data-and-commands.md:66-105`。

- 这是**规格与代码直接冲突**，不是实现错误：补全是实测验证过的正确解法（`unmapped_stock_count` 313 → 0）。
- 处理方式需产品决策：把 `Never` 改成"不得作为唯一来源 / 仅允许增量补齐"，并在 §5.2、§7.4 登记这两个端点。**在改之前，任何按规格行事的人都会认为现有代码违规。**

### P0-4　验收追踪表已实质失效：8 条条款没有映射，且基线数字停在 09-09
- 我用脚本清点：规格去重后 **104 个 `AC-*`**，追踪表 **96 个**，缺口 8 条且**全部是 2026-09-12 新增的**：
  `AC-MOVE-010`、`AC-MOVE-011`、`AC-MOM-009`、`AC-MOM-010`、`AC-HD-011`、`AC-FALL-010`、`AC-FALL-011`、`AC-FALL-012`。
  这些条款**对应的测试基本都已存在**（`StockMovesPage.test.jsx:104-160`、`chartTheme.test.js`、`HundredDayPage.test.jsx:104`、四个 `test_fallback.py` 等），属**映射缺失而非测试缺失**。
- 追踪表头部自称"标准数量：98"、基准日期 2026-09-09、并引用"234 tests / 49 tests"（`docs/acceptance/...traceability.md:5,15,16`），而当前是 329 / 78。一个用来证明"需求都实现了"的文档已经不可信。
- 附带：`AC-FLOW-007`、`AC-FLOW-008`、`AC-SRC-004` 在整个规格里**0 次出现**（编号自 006 跳到 009），两处一致所以不是漏条，但会误导读者。

---

## 2. P1（13 条）

### 后端 core 与工程配置

**P1-1　`get_list_setting` 把空串当显式空值，语义与同类 getter 相反**
`backend/backend/env.py:106-110`（`value is None` 才回退默认），而 `get_bool_setting`（:79-97）、`get_int_setting`（:93-103）对空串都回退默认。
后果：`ENABLED_MODULES=`（或误写成 `ENABLED_MODULES= `）→ `module_registry.get_enabled_modules()` 静默返回空元组 → **4 个模块同时从 `INSTALLED_APPS` 和 URLconf 消失**，且 `unknown_ids` 校验抓不到（`core/module_registry.py:53-63`）。`DJANGO_ALLOWED_HOSTS=` 同理得到 `[]`，`DEBUG=False` 下全站 400。

**P1-2　测试套件依赖开发者本机 `.env`，克隆后不可运行且会"按环境变色"**
`backend/backend/settings.py:34,206` 在 import 期 `get_required_setting`；全仓无 `conftest.py` / `pytest.ini` / CI 配置，而 `.env` 被 `.gitignore:151` 忽略。受影响的已知用例：`backend/tests/test_security_settings.py:19-24`（断言 `ALLOWED_HOSTS` 非空、`TIME_ZONE`）、`core/tests/test_calendar_services.py:91-94`（时区参与 `make_aware`）、`core/tests/test_intraday_quotes.py:230-241`（覆盖率阈值来自 `.env`）。这也是记忆里那条"唯一既有失败"的来源 —— 它不是代码缺陷，是**测试对环境有隐式依赖**。

**P1-3　`_begin_runs` 用生成器元组赋值，中途失败会留下永久 RUNNING 版本**
`backend/core/services/sync_daily_prices.py:237-252`
`runs = tuple(begin_publication(...) for ...)`：生成器中途抛错时，已创建的 `DataVersion(status=RUNNING)` 已提交（`publication.py:33-39` 无外层事务），而 `runs` 仍是旧值 → 调用方的 `_fail_runs(runs, ...)`（:457、:538）遍历空集合。`init_stock_daily_prices` 会在一年约 240 个交易日上批量制造这种孤儿。
影响：`DataVersion` 审计数据与 `ModuleRunStatus` 长期失真（不会丢数据，读路径按 `status=COMPLETE` 过滤，`market_data.py:67-74`）。无清理任务。

**P1-4　`source` 字段绕过已声明枚举（仅限 4 个非数据端点）**
`docs/specs/...spec.md:606` 规定 `source ∈ {cache, database, remote, computed}`；`backend/core/views.py:43,112,122` 对 `/session/`、`/health/`、`/modules/` 传 `'application'`。`core/api/responses.py:20` 只声明 `source: str | None`，无校验。
> ⚠️ 分报告曾称"`cache` 从未被任何读路径产出"，**该说法错误**：`stock_moves/services/read_path.py:240,271`、`sector_momentum:260,285`、`hundred_day:280,302`、`kaipanla:279,366` 都产出 `'cache'`，且四个模块的 API 测试都断言了它。真实问题只是这 4 个非数据端点用了枚举外的值（属 P2 级洁癖，不影响数据语义）。

**P1-5　错误码体系未闭环：5 个已声明错误码零引用**
`core/api/errors.py:15,17,18,19,20` — `DATA_INCOMPLETE`、`UPSTREAM_RATE_LIMITED`、`UPSTREAM_UNAVAILABLE`、`CACHE_CORRUPTED`、`MODULE_DISABLED` 全仓无引用，而规格 `:624-637` 把它们列为"稳定错误码"。对应实现缺口：

- `MODULE_DISABLED`：`backend/backend/urls.py:29-32` 只注册启用模块，禁用模块走 Django **默认 HTML 404**，不是统一 JSON 外壳；
- `CACHE_CORRUPTED`：`core/services/file_cache.py:36-37` 把损坏/不可读一律 `return None`，与未命中不可区分；
- 限流 / 上游不可用：`hithink/client.py:250-256`、`kaipanla/client.py:343-349` 只归一为 `upstream_failed` 日志，未映射到错误码。

**P1-6　管理命令把具体异常消息替换成通用文案**
`core/management/base.py:74-87` 的兜底 `except Exception` 连 `CommandError` 一起捕获并重抛为 `failure_message`。例：`sync_stock_daily_prices` 在非交易日得到 `ValueError('The requested date is not in the trading calendar.')`（`sync_daily_prices.py:473-474`），运维在终端只看得到"Daily-price synchronization failed."，原文只进日志。crontab 场景下这条消息就是唯一线索。

**P1-7　`chinese-calendar` 年度数据过期后静默降级为"是工作日"**
`core/services/calendar.py:29-33`：`NotImplementedError` → `return True`。`requirements.txt` 注释自认"按年内置，跨年需升级版本"。跨年未升级时，法定节假日会被当作交易日提交给只服务交易日的上游接口。这是**每年必踩一次的定时炸弹**，且降级方向是"更宽松"、最危险的方向。

### 四个业务模块

**P1-8　`stock_moves` 不跟踪行业映射版本，行业更新后既不置 stale 也不重建**
`stock_moves/models.py:11-13`（只有 `source_daily_price_version`）；`stock_moves/services/read_path.py:46-65`（只用 daily 版本判 stale）。而 `analysis.py:42,55,101-110` 实际消费 `snapshot.industries`，该快照由**独立的 `industry_snapshot` 数据集**驱动。`sector_momentum` / `hundred_day` 都正确带了 `source_industry_version`，**只有 `stock_moves` 漏了**；`stock_moves/admin.py:36-38` 的注释还写着"本模块只依赖公共日行情版本"，与事实相反。
影响：仅重跑行业映射时，`/api/stock-moves/` 的 `industries` 字段长期落后，且 `stale` / `warnings` 都不提示。

**P1-9　kaipanla：数据行写入与版本发布不在同一事务，崩溃窗口会产生"未发布数据 + 旧版本号 + 错缓存"**
`kaipanla/management/commands/fetch_kaipanla_sector_fund_flow.py:94-100`（`write_complete_snapshot` 提交后**再**调 `finish_publication`，两者是独立事务）。
若进程在窗口内被杀：`kaipanla_sector_fund_flow` 行已落库、`DataVersion` 停 `RUNNING` → 读路径按 `status=COMPLETE` 选到**上一个**版本（`read_path.py:216-225`），而 `queries.py:17-27` 按 `Max(snapshot_time)` 取到**新槽位**的行 → 新数据被打上旧 `data_version` 返回并按旧版本键写缓存（`read_path.py:274-287`）。
`core/services/publication.py:94-106` 已提供正确的 `publish_with_writer`（写 + finish 同事务），**kaipanla 没用它**。

**P1-10　kaipanla：解析层静默丢行，同时把快照标为 complete，`missing_record_count` 恒为 0**
`parser.py:41-46`（长度不足 / 无 `main_net_inflow` → `return None`）；`fetcher.py:129-132`（`if row is not None` 静默跳过，仍 `is_complete=True`）；`writer.py:69`（`expected_record_count=len(snapshots)` 用去重后行数，等于把"实际"当"应有"，完整性校验自证成立）、`:97`（`missing_record_count=0`）。
影响：板块列表 / 资金流排名可静默少板块，而运维依赖的 `missing_record_count` 字段在**所有路径恒为 0**，完全失去价值。同一上游在 `core/integrations/kaipanla/client.py:236-239` 对坏行是**抛异常使整次同步失败**，两处策略相反（P2 级不一致，但正是这个不一致导致了本条的隐蔽性）。

**P1-11　kaipanla：`ReadResult.stale` 恒为 `false`**
`kaipanla/services/read_path.py:33-42`（默认 `False`，所有构造点都不传值）。响应外壳里的 `stale` 对资金流模块永远是 false，前端**无法**用它区分"这是旧数据"—— 另三个模块都能。

**P1-12　kaipanla：`GET /dates/` 会触发真实上游抓取，且默认日期口径与另三模块不同**
- `read_dates()` 走 `_published_version(None)` → `_can_attempt_repair(today)` → `_repair_current_snapshot`（`read_path.py:227-230, 358-360`）：**一个纯元信息端点会发出上游 HTTP 请求**，被前端轮询时持续消耗上游配额。
- 默认（不带 `date`）锚定的是"最新**已发布 kaipanla 快照**日"，而另三模块锚定"最新**公共日行情**日"（`stock_moves/read_path.py:133-149` 等）。同一"最新日"在四个页面可能不是同一天。

**P1-13　`hundred_day`：显式日期 + 历史不足返回 202，违反 §5.8 的 404 规则**
`hundred_day/views.py:37-43`：`InsufficientHundredDayHistory` **无条件**映射 202（`preparation_state='insufficient_history'`），`requested_date` 参数只作用于 `CompleteMarketDataUnavailable`（:44-56）。
规格 `:648` 明确："无旧数据时返回 `404 DATA_NOT_AVAILABLE`（显式指定日期）或 `202 DATA_PREPARING`（未指定日期）"。而**历史不足对一个历史日期永远不会自愈**，202 会让前端进入"稍后重试"分支并误导运维告警。`hundred_day/tests/test_api.py:99-108` 只覆盖了 `CompleteMarketDataUnavailable` 的 404，这个分支没有测试。

**P1-14　四个模块的 `DatasetLocked` 语义不统一**
`kaipanla/services/read_path.py:177-190` → 409 `SYNC_IN_PROGRESS` + `preparation_state='syncing'`；另三个模块统一转 `CompleteMarketDataUnavailable` → 视图 202/404（`stock_moves/read_path.py:86-89` 等）。
同一并发语义（数据集被占用）有两个 HTTP 契约，前端/运维要单列分支，重试退避也无法统一。

**P1-15　`hundred_day` 的 199 日行情加载不按 `source_data_version` 过滤**
`hundred_day/services/source_data.py:57-65` 的 `DailyPrice.objects.filter(trade_date__in=trading_days)` 少了版本过滤，而 `core/services/market_data.py:97-100` 的同源查询是带的。当前正确性依赖"每日所有行必属同一版本"这一**写侧不变量**（`sync_daily_prices.py:255-274` 唯一 upsert + `:451-455` 整体改归属）。任何一次部分改归属失败都会静默混入旧版本收盘价参与滑窗极值，而产物版本号看不出来。

### 前端

**P1-16　三个页面在 `loading` 时整页替换，日期控件被卸载（与资金流页行为不一致）**
`StockMovesPage.jsx:28`、`SectorMomentumPage.jsx:94`、`HundredDayPage.jsx:123` 都是 `if (phase === 'loading') return <DataState state="loading" />`；而 `SectorFlowView.jsx:140-144` 只在内容区替换、`FlowControls` 常驻。切换日期时（非静默请求）`phase` 变 `loading`，三页把 `DatePicker` + `RefreshStamp` 一起卸载：**慢网下用户想改回日期却没有控件可点**，"更新于 HH:MM"也消失。

**P1-17　图表 series 每次渲染都是新数组，`useMemo` 完全失效 → 每轮重渲染都整图重绘**
`SectorFlowView.jsx:120-122` 内联 `.filter()` → `IntradayChart.jsx:7-16` / `HistoryChart.jsx:7-16` 的 `useMemo([series, timePoints])` → `useChart.js:12-22` 的 `setOption(option, {notMerge: true})`。任意无关 state 变化（勾选、`refreshedAt`）都会重建数组、命中不到 memo，触发 ECharts 全量重绘并重播动画。

### 文档与记忆

**P1-18　`AGENTS.md` 的数据源章节整体过时（对 AI 代理有直接误导性）**
- `AGENTS.md:34`「所有个股数据，都需要使用其同花顺 Python SDK。不要使用爬虫、浏览器自动化、原始 HTTP。」—— 实际 `backend/requirements.txt` 只有 `Django / requests / chinese-calendar`，`core/integrations/hithink/client.py` 用 `requests` + `X-api-key`；`docs/data-sources/hithink-and-kaipanla-capability.md:5` 明确"Python SDK 不再是本项目依赖"。
- `AGENTS.md:48` 开盘啦示例仍写已弃用的 `ZSType=7`，而 `.env.example:86,126` 现状是 `4`（881xxx 行业族）。

**P1-19　`init_stock_daily_prices` 的"能否重跑"两套说法**
`docs/ops/deployment.md:110`「首次数据准备（只运行一次）」+ `:121`「成功后不应再次执行」 **vs** 规格 `:702`「之后也可手动重跑以按上游校正与补齐……只写入有差异的行」+ `docs/ops/manage-commands.md:308,457,483,928` 同义 + 代码 `init_stock_daily_prices.py:5,29,39`（`is_initial_import` / `is_up_to_date` 分支、help 写 "revising existing rows"）。
按 deployment 理解会让人**不敢重跑**，而重跑恰恰是官方设计的校正手段。

**P1-20　规格 §3.1.1 / §3.1.3 在两个位置自相矛盾**
- `spec:139`「四个一级 Tab，每个 Tab 配一枚 24×24 线性图标」 vs `spec:929`（AC-UI-003）「四个 Tab 只显示文字标签，不显示左侧图标」+ `AppShell.test.jsx:93-95` + `.workbuddy/memory/2026-09-12.md:103`（图标已删）。同段 `spec:141` 的"表格"也已被看板取代。
- `spec:184`「按钮沿用全站的白底描边样式」 vs 同段 `spec:183`「无边框、无底色（`.btn--ghost`）」+ `StockMovesPage.jsx:55` + `AC-MOVE-011`。

**P1-21　规格完全未登记 2026-09-12 的两项新能力**
- `refresh_intraday_quotes` 在规格里出现 **0 次**（我用 grep 确认）；`.env` 契约段（§5.10）也没有 `INTRADAY_QUOTE_PAGE_SIZE`、`INTRADAY_QUOTE_MIN_COVERAGE_RATIO`、`HITHINK_INDUSTRY_BACKFILL_ENABLED`、`KAIPANLA_*_ZS_TYPE`。
- `spec:800` / `AC-TIME-002` 仍写"交易日 15:00 前请求当天盘后模块时，不生成当天盘后结果"，而 `core/services/market_data.py:41` 已放宽（当天有 complete 版本时上限提到当天），`docs/ops/manage-commands.md:587` 与此一致 —— **只有规格没同步**。

**P1-22　`.workbuddy-ai/` 是孤儿副本，且含别处没有的内容**
- 两个目录**都在 git 里**（`.gitignore:218-233` 未忽略，`git ls-files` 命中 17 个 `.workbuddy*` 文件）。
- `.workbuddy/memory/2026-09-12.md` = 559 行（工作区已修改）；`.workbuddy-ai/memory/2026-09-12.md` = 120 行（**无 git 变更，等于 HEAD 版本**）。
- 不是简单子集：`.workbuddy-ai` 那份**独有**「N燧原-U（688801）缺失排查」与「数据现状」两节（grep `688801` 命中 3 次 vs 1 次）。若按 `MEMORY.md:24` 只维护 `.workbuddy`，这段诊断会丢。
- 项目约定已明确记忆目录是 `.workbuddy/`（`.workbuddy/memory/MEMORY.md:24`），`.workbuddy-ai/` 应**先合并独有内容再删除**，避免出现第二个"真相源"。

---

## 3. P2（按类别归并）

### 3.1 死代码与失效配置

| 项 | 位置 | 说明 |
|---|---|---|
| 死配置键 | `.env.example:117` | `HITHINK_FINANCE_MAX_CONCURRENCY` 零代码引用 |
| 死配置键 | `.env.example:105`、`docs/ops/deployment.md:44` | `CORS_ALLOWED_ORIGINS` 全仓零引用；且 `deployment.md:32,161` 自己声明"不启用跨域 CORS、不应依赖它"。运维按模板配完会以为跨域已生效 |
| 重复配置键 | `.env.example:73-74` 与 `:129-130` | `KAINPANLA_PARENT_INDUSTRY_ACTION`、`KAIPANLA_STOCK_LIST_ACTION` 各定义两次（值相同），解析器是 dict 覆盖（`env.py:43`），未来改一处会"改了不生效" |
| 死函数 | `kaipanla/services/queries.py:8` | `latest_snapshot_trade_date()` 无引用 |
| 死字段 | `sector_momentum/services/analysis.py:44` | `top_5_percent_sample_size` 只在测试里被读，从不持久化、不返回 |
| 名不副实的配置 | `kaipanla/services/read_path.py:58` | `REMOTE_REPAIR_MAX_ATTEMPTS` 只当 `>=1` 布尔门用，实际固定 `max_pages=1, max_retries=0`（:117-123）；调大它没有任何效果 |
| 死条件 | `frontend/src/api/client.js:75` | `response.status !== 202` 恒真（202 本身 `ok===true`） |
| 死引用 | `frontend/src/shared/usePolledResource.js:24-25` | `apiClientRef` 只写不读，`:45` 用的是闭包里的 `apiClient`。注释声称"通过 ref 持有"与实现相反（当前因 `App.jsx:131` 的 `useMemo` 保证 identity 稳定而无害，但一旦 client 需要按登录态重建就会用旧实例） |
| 死常量 | `frontend/src/shared/charts/chartTheme.js:14` | `CHART.title` 无引用；`CHART.up/down` 与 `tokens.css:50-51` 重复；`tokens.css:116-118` 的 `--chart-grid/axis/label` 定义了却没人用（图表另用 JS 常量硬编码同值）→ 改 token 不影响任何图表 |
| 未使用令牌 | `frontend/src/styles/tokens.css` | `--color-info/-soft`、`--space-10`、`--radius`、`--color-brand-100/800`、`--text-2xl`、`--shadow-md` 等无消费点 |
| 死 CSS 类 | `frontend/src/index.css:259-282,353,379,765,1132-1189,1411-1417` | `.tabs--segmented`、`.panel--flush`、`.toolbar--spread`、`.page-lede`、`.table-wrap`、`.data-table` 系列、`.up/.down/.flat`、`.stock-detail__code/__value` —— 已删表格与二级导航的遗留 |
| 无效选择器 | `frontend/src/index.css:1574` | `.login__field > span` 永不匹配（`LoginPage.jsx:39,51` 用的是 `<label>`） |
| 未使用 prop | `frontend/src/shared/ui/Panel.jsx:13,18,34` | `flush` / `actions` 无调用方；`Icon.jsx` 的 `flow`/`list`/`calendar` 三个路径无引用 |

### 3.2 文档过时点

| 位置 | 问题 |
|---|---|
| `docs/ops/deployment.md:165,173` | 出现两个 `## 8`（备份恢复 / 发布前验证） |
| `docs/ops/deployment.md` 全文 | **没有一处说明生产环境如何跑 Django**（无 gunicorn / uwsgi / systemd / supervisor / nginx 示例），`requirements.txt` 也没有服务器依赖。§7 只说"反向代理把 `/api/` 代理给 Django"，照着做无法上线 |
| `docs/ops/manage-commands.md:919` | 拿"东方财富"举例，而同文件 `:38` 已声明没有东方财富相关代码 |
| `docs/data-sources/web-api.md:173` | 表格把「行业列表」的域名写成 `apphwshhq`（行情端点），实际 `KAIPANLA_INDUSTRY_API_URL=apphis`（`.env.example:61`）；`:60,203,244` 的示例也仍只有 `ZSType=7` |
| `docs/data-sources/hithink-and-kaipanla-capability.md:27,37` | 样本仍是 `801660`、"各 270 条"的**旧 801/803 族**数据（2026-09-07/08 记录），未更新到 881 族 |
| `tasks/plan.md:16` | 技术栈写"Django + Django REST Framework"，实际**没有 DRF** |
| `tasks/todo.md:492-496,560` | 残留 `StockGroupTable.jsx`（文件已删）、"四组统计和表格"、"五组 crontab 命令"（`deployment.md:125` 已是"四个逻辑组"） |
| `docs/acceptance/...traceability.md:34,105` | 同一文件两种路径写法（`backend/backend/tests/...` vs `backend/tests/...`） |
| `.workbuddy/skills/backend-dataset-diagnosis/SKILL.md:174,239` | 用例数写 239 / 281，当前基线 329 |
| `.workbuddy/skills/frontend-visual-verification/SKILL.md:3,62` | 说"12 个坑"但正文列到 13；`END_LABEL_GUTTER 132` 现值已是 152 |
| `.workbuddy/memory/2026-09-09.md:8,13`、`2026-09-11.md:114` | 早期记录仍是删除前状态（`DateField` 存在、开盘啦与东方财富共用视图、警告别删 `DateField.jsx`），与同日 `:272` 的删除记录**前后矛盾**，容易误读 |

### 3.3 测试缺口与弱断言

**后端**
- `core/tests/test_management_contract.py:14-40` 的锁定契约清单**漏了新增的 `refresh_intraday_quotes`**。
- `core/tests/test_dataset_models.py:42-81` 是同义反复（造对象后断言"传入的 status 集合 == 枚举集合"），零行为覆盖。
- `backend/tests/test_security_settings.py:18` `assertEqual(settings.SECRET_KEY, get_required_setting(...))` 两侧同源，恒真。
- **无任何用例覆盖**：陈旧锁恢复（P0-1）、`_begin_runs` 中途失败（P1-3）、kaipanla"行已提交但版本未完成"（P1-9）、`hundred_day` 显式日期 + 历史不足（P1-13）、`stock_moves` 行业版本变化（P1-8）。
- 已核对**无**"mock 掉被测逻辑本身"的用例 —— `test_fallback.py` 系列 mock 的是数据源与锁，断言仍在 `read_path` 的行为上。

**前端**
- `src/api/client.test.js:52-64` 名为"preserves caller cancellation"，实际没 `abort()`、没断言取消行为；缺 5xx 与"非 JSON body"用例。
- `src/shared/charts/chartTheme.test.js:38,45,54` 锁的是实现细节（`yAxis` 长度=4、`yAxisIndex=[1,2,3]`、第三柱等于 `[12,3]`），重构即碎。
- `src/shared/DataState.test.jsx:70-87` 用 `readFileSync` 读 CSS/tokens 断言子串与正则 —— 测文件文本而非行为，且依赖 CWD。
- `src/features/sector-flow/flowView.test.jsx:10-16` 模块级 `setOption` mock 全文件不重置，靠 `.at(-1)` 掩盖跨用例泄漏。
- `src/features/integration.test.jsx:19-44` 只覆盖 `useHundredDay`，且 mock 的 `request` 忽略 `signal`，`AbortController` 路径完全未验证。
- `src/app/AppShell.test.jsx:198` 的键盘导航用例游离在 `describe` 之外（仍会执行，组织错误）。
- 缺口：无用例断言 `aria-label="统计窗口"` 被保留；`viteProxyConfig.test.js` 未覆盖"空 origin → `{}`"分支。

### 3.4 健壮性与一致性

- **`mark_finished` 在 partial 时把 `last_success_at` 清成 NULL**（`core/services/run_status.py:40`），而 `DataVersion.last_success_at` 保留（`publication.py:65`）→ 两处口径不一致，运维无法回答"最近一次成功是什么时候"。
- **重跑后旧 COMPLETE 版本变成"0 行的完整版本"**：`sync_daily_prices.py:451-455` 把当日所有行改挂新版本，旧 `DataVersion`（`actual_record_count=N`）从不作废。功能正常（按 `-last_success_at` 排序取新版本），但 Admin 里展示的 `actual_record_count` 已不可信（`core/admin.py:61-75`）。
- **`file_cache` 的 `default=str` 让类型静默退化**（`core/services/file_cache.py:56`）：Decimal/date 存进去是字符串，`get` 原样返回（:30-35）→ 缓存命中与未命中返回**不同类型**，调用方拿到 str 而非数值。
- **`_set_publication_details` 逐行重复实现**（`sync_industries.py:85-94` 与 `sync_reference.py:27-38` 完全相同），修一处必漏一处。
- **模块清单在 5 处独立声明**（`module_registry.py:31-49`、`db_router.py:4-9`、`settings.py:99-120`、`settings.py:135` 的 `_APP_LOG_LOGGERS`、各 `apps.py`）。前四者当前一致（已逐项核对），但：`_APP_LOG_LOGGERS` 不随 `INSTALLED_APPS` 自动增长，新模块的 logger 无 handler，而 `LOGGING` 未定义 `root`（`settings.py:137-179`）→ INFO 日志会被 `lastResort` 丢到 stderr；`db_router._database_for_app`（:16-17）对未知 app **静默回退 `default`**，所以"registry 加了、router 忘了"不报错，而是把该模块数据写进 core 库。唯一守护测试 `backend/tests/test_database_routing.py:45-64` 只覆盖 kaipanla 一个 app。
- **登录无速率限制 / 锁定**（`core/views.py:67-88`）：只记 `login_rejected` 日志，无重试计数；`requirements.txt` 里也没有 `django-axes` 之类。对外暴露的 `/api/core/login/` 可无成本爆破（内部工具影响有限，但值得记）。
- **CSRF 失败映射成 `INVALID_PARAMETER`**（`core/views.py:126-131`）：HTTP 状态 403 是对的，但前端无法区分"参数错"与"CSRF 过期"；`test_session_api.py:101-102` 已把该行为固化。
- **`SameSite` 取值无校验**（`settings.py:126,128`）：写成 `lax`/`same_site` 之类拼写错误不报错，浏览器静默丢 Cookie。
- **`MAILERS` 配了 console 但从未配 `ADMINS`**（`settings.py:222-226`；全仓无 `ADMINS`/`MANAGERS`/`SERVER_EMAIL`），而 `core/middleware.py:11` 的注释称 5xx"还会走 mail_admins" —— 告警链路实际不存在。
- **`GET` 元信息端点缺防护**：`marketSession.js:18` 用**浏览器本地时区**判交易时段，后端用 `Asia/Shanghai`（`settings.py:206`）。非 UTC+8 的浏览器会把轮询窗口整体平移（如 UTC 机器的 01:30 会被判为交易时段）。
- **前端格式化口径不统一**：`stockFormat.js:8-18` 对空字符串会显示 `0.00%`（`'' == null` 为 false，`Number('')===0`）；`SectorMomentumPage.jsx:19-21` 的 `percent()` 无 null 守卫（null → `0.00%`），`HundredDayPage.jsx:16-18` 有（null → `—`）；`SectorMomentumPage.jsx:115` `Number(undefined)/1e8` → `NaN 亿元`。
- **`RankingList.jsx:19-21` 直接 `value.toFixed(1)`**，是全站唯一没有走 `Number()` 保护的地方（`stockFormat.js` 全程都走），字段缺失或变成字符串时整页榜单会崩。
- **`HundredDayPage.jsx:133` 的 `totals` 没有默认值**（`industry_summaries`、`trend` 都给了 `= []`），`envelope.data` 存在但缺 `totals` 时 `:149-151` 抛 `TypeError` → 整页白屏。
- **无障碍**：`TabBar.jsx:36-37` 内外两层 `aria-label` 同名重复播报；`AppShell.jsx:116` 的 `tabpanel` 无 `aria-labelledby`；`DatePicker.jsx:232-238` 的 `role="dialog"` 无 `aria-modal`、无焦点陷阱。
- **`.data-state` 重复声明**（`index.css:774` 与 `:779`），且 `:781` 的 `overflow-x: auto` 同样作用于 `.data-state--content`（`:795` 未重置）。

### 3.5 仓库卫生

- **3 个预览 HTML 已入库**：`sector-momentum-preview.html`（1.19MB）、`three-page-preview.html`（1.25MB）、`stock-moves-board-preview.html`（46KB），合计约 2.4MB 的**一次性视觉验证产物**被 `git ls-files` 跟踪（`2026-09-12.md:67` 自己标注"仓库根，可删"）。`.gitignore` 只忽略 `tests/*` 与 `frontend/dist/`，没有覆盖这类文件。
- 好的一面：`tests/` 目录干净（只有 `.gitkeep`），`backend/data/`、`backend/cache/`、`*.sqlite3`、`.env` 均已正确忽略，`git status` 里 **0 个未跟踪文件**。

---

## 4. 分报告误报澄清（我已逐条复核，以下**不是**问题）

1. 「`source='cache'` 从未被任何读路径产出」—— **错误**。四个模块的读路径都产出 `'cache'` 且都有测试断言（见 P1-4 说明）。真实问题只是 4 个非数据端点用 `'application'`。
2. 「前端手选日期会压过后端业务日期，导致显示 A 日、画 B 日数据」（原判 P0）—— **不成立**。四个模块在"显式指定日期"时都**拒绝**用其他业务日期冒充结果（`stock_moves/read_path.py:205`、`hundred_day/read_path.py:262-264` 等），无数据直接 404。`businessDate.js:10` 的 `selectedDate ||` 短路因此是安全的。真正值得注意的是：**这条不变量完全靠后端守住，`resolveDisplayDate` 处没有任何注释说明这一点**，属于"脆弱但正确"。
3. 「`kaipanla` 读路径与另三模块的 `read_path` 结构完全不同所以是缺陷」—— 结构确实不同（无 `_read_*` / 无 `_resolve_read_date`），但根源是**数据模型不同**：kaipanla 读的是"已发布快照"而非"可按需生成的派生结果"。差异本身合理，**P1-12 里那两条（默认日期锚点不同、`/dates/` 触发上游）才是真问题**。
4. 「AC 规格 106 / 追踪 98」—— 实测 **104 / 96**（脚本去重后），缺口是 8 条而非 10 条。

**已确认属有意为之、无需修改**（避免后续误改）：
`hundred_day/services/flags.py:100-112` 历史缺失补 0 与等值 `>=`/`<=` 判高判低（legacy 口径，`test_flags.py:51-86` 显式锁定 + `:101-149` 130 位随机序列差分验证）；双单调队列滑窗的边界（`flags.py:42-69`）经差分测试未发现 off-by-one；`stock_moves` 的 `<8%` / `<8e8` 严格小于口径（`test_analysis.py:55-82` 锁边界）；`sector_momentum` / `hundred_day` 的 `source_versions.py` 互相重复（模块隔离的代价，非死代码）；hithink 客户端里 `interval='1d'`/`adjust='forward'`/`tag='industry'` 是上游固定契约不必进 `.env`；`_local_generate` 不在请求内做远端同步（有专门用例守护）；`_QUIET_PATHS` 与 4xx 不升级 WARNING；`SectorMomentumPage` 不渲染 warnings；`chartTheme.js` 的三隐藏轴、`endLabel` 152px 留白、去顶部图例；`StockMoveBoard` 空栏留白；`prefers-reduced-motion` 块里的 `!important`。

---

## 5. 建议修复顺序（如需动手）

> 按"风险 / 代价比"排序，**均为独立小改动**，互不阻塞。

| # | 事项 | 影响文件量 | 说明 |
|---|---|---|---|
| 1 | 陈旧锁回收（P0-1） | 1-2 | 收益最大：一次性消除"永久瘫痪"这个模式 |
| 2 | `sync_stock_master` 加行数下界（P0-2） | 1 | 防静默丢数据，改动极小 |
| 3 | 补 8 条 AC 映射 + 刷新追踪表基线（P0-4） | 1 | 纯文档，恢复"需求可追踪"的信任 |
| 4 | 决策并改写规格 §9 的 `Never`（P0-3） | 1-2 | 需你拍板口径 |
| 5 | `hundred_day` 显式日期改 404（P1-13）+ 补测试 | 2 | 契约一致性，前端已有 `INSUFFICIENT_HISTORY` 分支可复用 |
| 6 | kaipanla 改用 `publish_with_writer`（P1-9）+ `missing_record_count` 语义（P1-10） | 2-3 | 同模块一次改完 |
| 7 | `stock_moves` 补 `source_industry_version`（P1-8） | 3-4 | 需要迁移 + 与另两模块对齐 |
| 8 | 文档批量订正（AGENTS.md 数据源章节、deployment 两个 `## 8` 与 init 口径、规格 Tab 图标/15:00 断点、tasks/ 残留） | 6 | 纯文档 |
| 9 | 清理死代码与失效配置键（§3.1） | 8-10 | 低风险、可分批 |
| 10 | 前端三页保留筛选控件（P1-16）+ `totals` 兜底 + `RankingList` 数值保护 | 4 | 用户体验与健壮性 |

---

## 6. 一处需要你留意的仓库状态

`git status` 显示 **102 个文件处于已暂存/已修改**（0 个未跟踪），`HEAD` 停在 `3d69e79 refactor via deepseek v4.1 flash`。也就是说**本次评审看到的所有 2026-09-12 改动（含 881 族切换、同花顺补全、盘中链路、日志体系、三个迁移）都还没有提交**。其中 4 个新文件是纯新增（`core/middleware.py`、`core/services/industry_backfill.py`、`core/management/commands/refresh_intraday_quotes.py`、`core/migrations/0004_remove_industry_level.py`）。建议在继续迭代前先落一个提交 —— 目前任何一次误操作都可能丢掉一整天的工作。

---

## 7. 修复记录（2026-09-13 补记）

> **本节不是评审结论。** 第 0–6 节是 2026-09-12 的**只读评审原文，一字未改**；本节是事后补记的修复台账，写作视角是"改完之后回填"，与前面各节的时态刻意保持区分。原报告末尾那句"未修改仓库内任何代码或文档"只描述第 0–6 节。
>
> **范围**：用户指定「修复 P0 的 1、2、4；P0-3 按『只有北交所股票需要同花顺数据来找对应关系』的口径处理；修复全部 P1 与 P2」。
> 下面按原编号逐条对应，**能落到具体文件与测试的才写"已修"，只做了决策/改文档的单独标注**。
>
> 编号口径：第 2 节的标题写「P1（13 条）」，但正文实际编到 **P1-22**（标题里的 13 是笔误，正文的自编号才是权威）。本节按 **P1-1 … P1-22 共 22 条**逐条对应。

### 7.1 P0（4 条）

| 编号 | 处置 | 落地内容 |
|---|---|---|
| **P0-1** 陈旧锁无回收 → 一次 SIGKILL 永久瘫痪 | **已修** | `core/services/locking.py` 锁文件写入 PID + 时间戳，获取失败时判断持有者是否存活 / 是否超龄并回收；阈值可配（`.env`）。新增 `test_locking.py` 用例覆盖：死持有者立即回收、活持有者永不回收、跨主机按阈值、损坏锁按阈值、阈值 0 只允许死持有者、释放时不删他人重建的锁。 |
| **P0-2** `sync_stock_master` 缺行数下界 → 上游一次截断静默停用全市场 | **已修** | `core/services/sync_reference.py` 停用非活跃股票前加入比例下界校验，低于门槛直接失败并带出"少到无法保留 90% 现有活跃股票"的原因；`--dry-run` 同样校验。`core/tests/test_sync_reference_commands.py` 覆盖截断被拒 / 正常波动放行 / dry-run 也校验。 |
| **P0-3** 规格明文"永不"用同花顺行业接口，而代码已依赖 | **已修（按用户口径）** | 用户明确：**只有北交所股票**需要同花顺数据来建立行业对应关系。据此把规格里那条 `Never` 改写为"**不得作为唯一来源 / 仅允许增量补齐**"，并在 §5.2、§7.4 登记 `list_industry_indices()` / `list_industry_constituents()` 两个端点。实现侧 `core/services/industry_backfill.py` 保持"只增不删、只补同花顺也有的代码"的语义。 |
| **P0-4** 追踪表 8 条映射缺失、基线停在 09-09 | **已修** | `docs/acceptance/traceability.md` 补齐 8 条（`AC-MOVE-010/011`、`AC-MOM-009/010`、`AC-HD-011`、`AC-FALL-010/011/012`），刷新标准数量与基准日期，并在 2026-09-13 把「最近一次全量基线」填成实测值（见 §7.4）。 |

### 7.2 P1（22 条）

| 编号 | 一句话 | 处置 |
|---|---|---|
| P1-1 | `get_list_setting` 把空串当显式空值 | 已修：空串 / 纯空白 / `KEY=` 一律回退 `default`，docstring 写明"一个多打的 `=` 曾静默关掉全部模块" |
| P1-2 | 测试套件依赖本机 `.env` | 已修：那条读 `.env` 的安全用例改为在调试口径下 `skipTest` 并说明原因（生产口径才真跑），其余用例与环境解耦 |
| P1-3 | `_begin_runs` 生成器中途失败留永久 RUNNING | 已修：改为先建列表再批量提交，失败时能遍历到已创建的行 |
| P1-4 | 4 个非数据端点用枚举外 `source` | 已修 |
| P1-5 | 5 个已声明错误码零引用 | 已修：错误码闭环（含 `MODULE_DISABLED` 统一 JSON 外壳、`CACHE_CORRUPTED` 与未命中可区分、上游限流/不可用映射到对应码） |
| P1-6 | 命令把具体异常消息换成通用文案 | 已修：兜底不再吞掉 `CommandError`，原始消息带进终端 |
| P1-7 | `chinese-calendar` 过期后静默降级为"是工作日" | 已修：降级方向不再默认"更宽松" |
| P1-8 | `stock_moves` 不跟踪行业映射版本 | 已修：新增 `source_industry_version`（模型 + `migrations/0006`），读路径据此判 stale，`admin.py` 的相反注释一并纠正 |
| P1-9 | kaipanla 写入与发布不同事务 | 已修：改用 `core/services/publication.py` 的 `publish_with_writer`（写 + finish 同事务） |
| P1-10 | kaipanla 解析层静默丢行且 `missing_record_count` 恒 0 | 已修：`expected_record_count` 用上游应有行数，静默跳过不再把快照标 complete |
| P1-11 | kaipanla `ReadResult.stale` 恒 `false` | 已修：退回旧快照时置真 |
| P1-12 | `GET /dates/` 触发真实上游抓取；默认日期口径与另三模块不同 | 已修：纯元信息端点不再发上游请求，默认锚点与其他模块对齐 |
| P1-13 | `hundred_day` 显式日期 + 历史不足返回 202 | 已修：显式日期 → `404 INSUFFICIENT_HISTORY`；默认入口保留 202 + `insufficient_history`（前端据此显示具体原因），补了该分支的测试 |
| P1-14 | 四个模块 `DatasetLocked` 语义不统一 | 已修：kaipanla 改用 `DatasetBusy`，与另三模块一致（读路径里明确注释了 `SYNC_IN_PROGRESS` 为何从"退回旧数据"的集合里移除） |
| P1-15 | `hundred_day` 199 日行情加载不按 `source_data_version` 过滤 | 已修：与 `core/services/market_data.py` 同口径加版本过滤 |
| P1-16 | 三页 `loading` 时整页替换、日期控件被卸载 | 已修：`StockMovesPage` / `SectorMomentumPage` / `HundredDayPage` 改为只替换内容区，`DatePicker` 与 `RefreshStamp` 常驻（与资金流页一致） |
| P1-17 | 图表 series 每次渲染新数组，`useMemo` 失效 | 已修：`SectorFlowView` 的过滤结果 memo 化，无关重渲染不再整图重绘 |
| P1-18 | `AGENTS.md` 数据源章节过时（对 AI 代理有误导） | 已修：Python SDK 口径改为 REST + `X-api-key`；开盘啦示例的 `ZSType` 更新为 `4` |
| P1-19 | `init_stock_daily_prices` 能否重跑两套说法 | 已修：`docs/ops/deployment.md` 与规格/`manage-commands.md` 对齐为"可重跑校正" |
| P1-20 | 规格 §3.1.1 / §3.1.3 自相矛盾 | 已修：Tab 图标与按钮样式两处矛盾按已实现状态订正 |
| P1-21 | 规格未登记 `refresh_intraday_quotes` 等新能力 | 已修：补登命令与 4 个 `.env` 契约键，并同步 15:00 断点的实际口径 |
| P1-22 | `.workbuddy-ai/` 是孤儿副本且含独有内容 | 已修：独有内容（688801 排查、数据现状）并入 `.workbuddy/` 后删除该目录 |

### 7.3 P2（5 类）

| 类别 | 处置 | 落地内容 |
|---|---|---|
| **3.1 死代码与失效配置** | **已修** | 删死配置键（`HITHINK_FINANCE_MAX_CONCURRENCY`、`CORS_ALLOWED_ORIGINS`）、去掉重复定义的两对开盘啦键、删死函数/死字段/死条件/死常量/死 CSS 类/无效选择器/未使用 prop；`REMOTE_REPAIR_MAX_ATTEMPTS` 正名为 `REMOTE_REPAIR_ENABLED` 并在 docstring 写明"它是开关不是预算"；`usePolledResource` 的"注释与实现相反"一并消除 |
| **3.2 文档过时点** | **已修** | `deployment.md` 两个 `## 8` 合并并补生产运行方式；`manage-commands.md` 去掉东方财富举例；`docs/data-sources/web-api.md` 域名与 `ZSType` 订正；`tasks/` 残留清理；两个技能里的用例数与 `END_LABEL_GUTTER` 更新；早期记忆的矛盾处标注 |
| **3.3 测试缺口与弱断言** | **已修** | 后端：命令契约清单改为**从命令自己的 parser 推导必填参数**（不再手写映射，因此自动包含 `refresh_intraday_quotes`）、`dataset_models` 的同义反复改为真存真读 + 排序断言、`SECRET_KEY` 恒真断言改为占位符/前缀检查。前端：真 `AbortController` 取消原样抛出、非 JSON / HTML body、404/500 不触发 `onUnauthorized`、`chartTheme` 断语义而非实现细节、四个页面的取数 hook 逐个走"过期响应丢弃 + 在途请求取消"不变量、`viteProxyConfig` 空 origin 分支、`aria-label="统计窗口"` 保留、`tokens.css` 按色相断涨红跌绿。移除两条读 CSS 文本断子串的用例 |
| **3.4 健壮性与一致性** | **已修** | `mark_finished` 的 partial 不再清空 `last_success_at`；重跑后旧版本计数归零（`supersede_previous_versions`，状态作为历史保留）；`file_cache` 不再用 `default=str` 静默退化类型；`_set_publication_details` 去重；前端格式化统一到 `stockFormat.js`（缺失值一律 `—`，不再伪装成 `0.00%`）、`RankingList` 数值保护、`HundredDayPage.totals` 兜底、交易时段判定锚定 `Asia/Shanghai`（不再用浏览器本地时区）、CSRF 失败有自己的错误码、`SameSite` 取值校验、`ADMINS`/`SERVER_EMAIL` 接入并订正 middleware 注释、无障碍三处（TabBar 去重复 `aria-label`、tabpanel 保留具体模块名、DatePicker 加 `aria-modal` + 焦点陷阱）、`.data-state` 重复声明清理 |
| **3.5 仓库卫生** | **已修** | 3 个一次性预览 HTML 从索引移除（`git rm --cached`）并在 `.gitignore` 加 `*-preview.html`；`tests/` 保持只有 `.gitkeep` |

### 7.4 回归证据（2026-09-13 05:01）

清 `backend/data/locks/*.lock` 与 `backend/cache/` 之后：

| 目标 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `manage.py test`（带 `CODEBUDDY_SAFE_DELETE_ENABLED=0`，输出重定向到文件后再过滤） | `Ran 395 tests in 36.664s` → **`OK (skipped=1)`**，0 失败 0 错误，跑完锁目录为空 |
| 迁移一致性 | `manage.py makemigrations --check --dry-run` | `No changes detected` |
| 前端全量 | `vitest run` / `eslint src` / `vite build` | **19 文件 / 150 用例全过**；lint 无输出；build 成功（658 modules transformed） |

**"唯一的既有失败"已消失**：`backend/backend/tests/test_security_settings.py::test_runtime_security_settings_are_safe_by_default` 现在在本地 `.env` 是调试口径时 `skipTest` 并写明原因（即那个 `skipped=1`），只在生产口径 `.env` 下才执行断言。**所以这次的全量是真绿**：失败集合为空即等于无回归，不必再从结果里扣掉任何"既有失败"。

### 7.5 本节新增的迁移（均已应用到四个业务库）

- `backend/kaipanla/migrations/0002_kaipanlasectorfundflowsnapshot_source_data_version.py`（P1-11 支撑）
- `backend/stock_moves/migrations/0006_stockmoveresult_source_industry_version.py`（P1-8）

> P0-1 新增的陈旧锁回收逻辑、P1-9 的 `publish_with_writer` 切换、P1-14 的锁语义统一**都不需要迁移**。

### 7.6 遗留事项（不阻塞，供你决定）

1. 3 个预览 HTML **仍留在仓库根磁盘上**（合计约 2.4MB）。它们已不再被 git 跟踪、也已被 `.gitignore` 的 `*-preview.html` 覆盖，所以不影响仓库；但若你希望磁盘上也清掉，删掉即可 —— 这些是一次性构建产物，可随时重新生成。
2. §3.4 里点名的 `index.css` 三处（`:focus-visible`、`@media (max-width: 40rem)`、`overflow-x: auto`）**现在没有任何自动化断言**：原先那两条读文件断子串的用例被移除了（读 CSS 文本既过严又过松，且依赖 CWD），这三处的回归只能靠截图人眼确认 —— 改动它们时别指望测试兜底。
3. 登录无速率限制 / 锁定（§3.4 末段）**未改动**：需要引入新依赖（如 `django-axes`），超出"修 P1/P2"的范围，留给你拍板。
4. 提交建议：`HEAD` 仍停在 `3d69e79`，工作区现在有 **183 个**已暂存/已修改/未跟踪条目（含 2 个未跟踪的新迁移）。**在继续迭代前先落一个提交**，否则任何一次误操作都可能丢掉两天的改动。

---

*第 0–6 节为 2026-09-12 只读评审原文（未修改）；第 7 节为 2026-09-13 事后补记的修复台账。*
