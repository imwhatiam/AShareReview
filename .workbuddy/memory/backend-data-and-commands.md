# 后端数据管道：交易日、上游、命令与性能（专题）

按需读取。**故障排查流程**（"命令成功但页面没数据"）见 `.workbuddy/skills/backend-dataset-diagnosis/SKILL.md`。

## 交易日、上游与快照

### 交易日判定：唯一来源、不落库、覆盖年份有硬顶

- **交易日判定只有 `core.services.calendar` 一处**：① 周末直接不是交易日（也覆盖"调休上班的周末"）；② 工作日的法定节假日由 **`chinese-calendar`**（已进 `backend/requirements.txt`）判定。该库**按年内置数据**，未覆盖年份退化为"工作日即交易日"并每年报一次 WARNING。**每年国务院放假安排公布后升级该包并重启服务**，不需要任何数据同步动作。
- **覆盖年份有硬顶**：`chinese-calendar` 只内置到某一年（当前固定的版本覆盖到 **2026**）—— `is_holiday(2026-10-01)` 正常，`is_holiday(2027-10-01)` 抛 `NotImplementedError`。**次年 1 月 1 日起全系统退化为"工作日即交易日"**，且**没有第二层兜底**（没有"退回上游交易日历"这条路）。后果不是纯静默：元旦当天会被当交易日，`refresh_intraday_quotes --latest` 或 `init_stock_daily_prices` 会去抓上游（整批发布失败），资金流会按 15:00 落一条假收盘快照。
- **该包的发布节奏固定**：**每年只发一个覆盖次年的版本，时间固定在 10 月底至 11 月中**，紧随国务院公布次年安排之后。所以"提前升级"通常做不到 —— 在那之前 `next_year_covered=false` 是**预期状态，不是待办**。
- **覆盖边界必须可观测，不要靠记性**（覆盖是**年粒度**的：某一年要么整年可用、要么整年不可用）：
  - `core.services.calendar.calendar_coverage()` 由 `covered_year_range()` 从 `chinese_calendar.holidays` 取年份闭区间，随 `GET /api/core/health/` 的 `data.trading_calendar` 返回 `covered_from` / `covered_through` / `covered_through_date` / `current_year` / `current_year_covered` / **`next_year_covered`**。**`next_year_covered=false` 就是"该升级依赖了"**，出现在跨年退化之前而不是之后。
  - `core/tests/test_calendar_services.py::HolidayTableCoverageTests` 是守卫：当前年份不被覆盖就变红，正确处理是**升级依赖，不是改断言**。
- **"日历为空 / 没同步到当天"这一整类故障不存在**：交易日永远可推导。`fetch_kaipanla_sector_fund_flow` 的盘中判定、`refresh_intraday_quotes` 的两道闸门、三个 `build_*` 的默认日期解析（`resolve_business_date`）、`hundred_day` 的窗口计算，统一调 `core/services/calendar.py`。**不要写 `timezone.localdate()` 当业务日期**。
- `latest_eligible_trading_day()` 与 `latest_trading_date()` 语义不同：前者问"当天收盘了没有"，**当天 < 15:00 时主动退一天**；后者只回答"最近一个交易日"。

### 快照时刻与槽位

- **快照时刻只有一处判定：`kaipanla.services.intraday.resolve_snapshot_slot(运行时刻)`**（管理命令、`--latest`、Web 补齐三处共用）。按运行时刻（**不用上游 `Time` 字段**）给唯一合法槽：盘中向前回退到所在 5 分钟槽（09:33→09:30）、午休回退 11:30、**盘后一律 15:00**、**非交易日与开盘前落到最近一个交易日的 15:00**（覆盖之，不写当天假收盘）。
- **槽必须是标准 5 分钟槽**：`query_intraday` 的 `time_axis` 只认 09:30–15:00，落在别处（如 15:05）的行读不出来 → 表现为"缓存失效了、数据却没变"。
- **kaipanla 快照"覆盖而非追加"的依据是表约束**：`UniqueConstraint(fields=['sector_code', 'snapshot_time'])`（`kaipanla/models.py`），**不是"15:00 槽"** —— 后者只适用于盘后 `--latest`。

### 上游日期参数与分页上限

- **上游日期参数必须落在交易日**：开盘啦**历史**端点（`KAIPANLA_INDUSTRY_API_URL` → `apphis`，与实时资金流 `apphwshhq` 是两条独立 URL）只服务交易日，传周末/节假日回 `errcode 1020 参数出错`。行业快照 `Date` 默认值由 `core.services.calendar.latest_trading_date()` 解析。上游非 0 `errcode` 会把 `errcode`/`errmsg` 带进异常消息。
- **开盘啦两个端点的分页 `st` 上限完全不同**：
  - 成分股 `ZhiShuStockList_W8` **无实际上限** → `.env` 用 `KAIPANLA_INDUSTRY_STOCK_PAGE_SIZE=300`（已对 2291 只的板块复验逐只一致）。提成分股分页只压得动分页请求，**每个行业至少一次请求**的下限压不掉。全量行业快照约 4 分钟（104 个 881 行业），必须后台跑。
  - 板块列表 `RealRankingInfo` 有**约 70 的隐性上限，`st≥75` 静默返回空列表**（客户端会当"分页结束"→板块被静默截断）→ `KAIPANLA_INDUSTRY_PARENT_PAGE_SIZE` **必须保持 30**。
- **资金流分页有硬上限 80**：`kaipanla/services/client.py::MAX_PAGE_SIZE = 80`，超过抛 `ImproperlyConfigured`（`KAIPANLA_FLOW_PAGE_SIZE must not exceed 80.`）。与行业成分股的 300 是两回事，**不要互相套用**。
- kaipanla 资金流 `main_net_inflow` 单位是**元**，读路径 `/1e8` 再 `round(...,4)`。测试数据用亿级（`Decimal('200000000')`）；写 `Decimal('20')` 会被四舍五入成 0，正负榜双双过滤掉，表现为"series 恒为空"的假 bug。

### 上游适配层的公共契约（改上游客户端前先读）

- **开盘啦两个端点共用一套异常与请求头**：唯一声明处 `core/integrations/kaipanla/contracts.py`（`KaipanlaUnavailableError` / `KaipanlaRateLimitError`（前者的子类，供 429 单独映射）/ `KaipanlaPayloadError` / `DEFAULT_USER_AGENT` / `request_headers()`）。行业适配器（`core/integrations/kaipanla/client.py`）与资金流适配器（`kaipanla/services/client.py`）都从这里导入，**`core/api/errors.upstream_error_code` 也只认这一套**。
- **不要在任何一侧重新声明同名异常类**。两侧各有一份同名但不同对象的类时，`isinstance` 跨不过去 ⇒ 资金流链路无论是被 429 限流还是上游挂掉，`upstream_failed` / `data_command_failed` 里的 `error_code` **恒为空**。回归由 `kaipanla/tests/test_fetcher.py::KaipanlaClientUpstreamErrorCodeTests` 三条守住（`assertIs` 同一对象 + 两类失败映射成两个不同错误码），**变异验证**过（重新声明同名类即变红并复现 `None`）。
- **`error_code` 一律由异常类型推出，不写死**（`upstream_error_code_value(failure)`）：429 → `UPSTREAM_RATE_LIMITED`、其余非 2xx / 网络异常 → `UPSTREAM_UNAVAILABLE`、payload 错误 → `None`（故意留空，不错标成"上游挂了"）。
- **请求头只有 `request_headers()` 一处**，`User-Agent` 读 `KAIPANLA_USER_AGENT`、**留空按"未配置"回落到 `DEFAULT_USER_AGENT`**（不发出空 UA 头）。全仓 `Dalvik/2.1.0` 字面量**只允许出现在 `contracts.py`**。
- **必需型配置读取只有 `backend/env.py`**：`get_required_int_setting(name, minimum=)` / `get_required_float_setting(name, minimum=)`（缺失或格式错 → `ImproperlyConfigured`，不做默认值兜底）。三个上游客户端（hithink / 开盘啦行业 / 开盘啦资金流）与 `kaipanla/services/fetcher.py` 都调它们，**不要在客户端里写私有校验副本**。

## 板块代码族：`ZSType` 才是选族的开关

`RealRankingInfo`（`c=ZhiShuRanking`）除 `Type` 外还有一个**大写 `ZSType`**，它是选"取哪一族板块"的开关：

| `ZSType` | 返回 | 条数 | 顶层 `list_son`/`list_soninfo` |
|---|---|---|---|
| 4 | **881xxx 行业**（元件 / 通信设备 / 半导体 / 银行…） | 104 | 空（扁平，无层级） |
| 5 | 885xxx / 886xxx 概念 | 499 | 空 |
| 6 / 8 | 801xxx **地域**（湖北省 / 北京市…） | 40 | — |
| 7 | 801xxx / 803xxx 开盘啦自编概念题材 | 270 | **有**（PCB / 光模块 / 覆铜板…） |
| 1/2/3/9–15 | 空 | 0 | — |

- **`Type` 不是族开关，是榜单口径**；而且 `Type=12/13/14` 会**越过 `ZSType`** 直接返回 80xxxx。要 88 行业必须固定 `Type=1`。
- **881 族是扁平结构（无层级）**：同代码族下不存在更细的一层。成分股照常可取：`ZhiShuStockList_W8` 需 `Type=6`（`Type=0` 返回空），`Index` 分页正常，`st` 直到 1000 都不截断。
- **`Count` 字段不可信**（有时是总条数、有时是当页条数）—— 客户端靠"行数 < page_size"判终止是对的，**别改用 `Count`**。
- **881 各行业之间有重叠**，不是互斥划分：881120 电力设备包含 881279 光伏设备的成分股；104 个行业成分股计数合计大于 A 股总数。**用它做行业归属前必须去重。**
- **同一 88 行业在两条端点上成分股不同**：实时 `apphwshhq` 带北交所，历史 `apphis` **不含北交所**（剔掉的全是 43/83/87 开头）。而 80xxx 概念走 `apphis` 是**带 920xxx 北交所的** —— "北交所缺失"只出现在 88 族 + 历史端点这个组合上。
- **切到 88 行业零代码改动**：只把 `.env` 的 `KAIPANLA_INDUSTRY_PARENT_ZS_TYPE` 改成 `4`（`sync_industries._collect_industry_snapshot` 直接按行业代码取成分股，无回退分支）。**代价**：88 行业与 801xxx 概念共用同一 dataset `industry_snapshot` 和同一张表，切换会覆盖既有快照，二者不能并存。

### 88 行业的板块资金流

板块资金流与行业列表**用的是同一个 action** `RealRankingInfo`（`c=ZhiShuRanking`），族开关同样是 `ZSType`。所以把 `.env` 的 `KAIPANLA_FLOW_ZS_TYPE` 改成 `4` 即可取 881 行业资金流，**不需要动代码**（`KAIPANLA_FLOW_TYPE` 必须保持 `1`）。

- 行结构与 80 族**完全一致（19 列）**，`parse_sector_row` 全部解析成功、无 `None`、主力净流入无一为 0。
- **`item[14..16]` 是族间唯一字段差异**：88 族恒为 0，80 族有值（"机构增仓 / 当年 PE / 次年 PE"）。这三列 `parser` 不读，不影响落库与页面，只是这两列在行业上不可用。
- **历史回补窗口只有 3 个交易日**（端点的滚动窗口）：实时 `apphwshhq` + `Date` 只有最近 3 天有数据，更早一律 `Count=0`。
- **`apphis` 历史端点对 88 族资金流完全空**（`errcode=0` 但 `Count=0`）。**行业列表用的 `KAIPANLA_INDUSTRY_API_URL=apphis` 与资金流用的 `KAIPANLA_API_URL=apphwshhq` 是两条端点，别混用** —— 88 族在两者上的可用性完全不同。
- 带 `Date` 请求历史时，响应里的 `Day` 仍是**最新交易日**（不随 `Date` 变），而 fetcher 的 `_source_metadata` 正是取 `Day[0]` 当业务日期 → **用 `Date` 回补会把旧数据落在新日期上**。项目现网不传 `Date`（靠定时落库），所以不触发。
- **不能与 80 族并存**：单次请求 `ZSType` 单选，且 `kaipanla_sector_fund_flow` 只有一个 dataset。切族会与既有 801/803 快照**混在同一张表**，`query_intraday_history`（1/5/10/20 日窗口）会把两族按 code 混排。要并存必须再加一个 dataset + 独立表。
- 前后端**没有任何板块代码前缀硬编码**，切族不会撞上写死的判断。

### 切换板块族必须配套清数据

**三个原因**：

- `write_complete_snapshot` 是按 `(sector_code, snapshot_time)` **upsert**，不删旧族 → 旧族的行会留在同一张表里混族。
- `core.services.market_data.get_complete_market_snapshot` 取 `IndustrySnapshot.objects.all()` **不按版本过滤** → 表里同时有两族行业时，三个模块的板块划分会两族混排。
- `sector_momentum` / `hundred_day` 的产物按输入判定，换族后旧产物要么过期要么被当有效。

**清理范围**：`IndustrySnapshot`、kaipanla 快照、三个模块的产物表、以及 `backend/cache/` 全部文件。**`stock_daily_prices` 与 `stock_master` 的数据必须保留**，删了要重跑同花顺全量。执行前先整库备份 `backend/data/`。

## 北交所行业归属：用同花顺行业成分股增量补齐

上游 881 族对北交所用的是**旧代码（43/83/87）**，与本地 `core_stock` 的 `920xxx` 对不上 → 只靠开盘啦会让北交所股票全部无法归入任何行业。**把 `KAIPANLA_INDUSTRY_API_URL` 换成实时端点修不好**（实时端点给 43/83/87 旧代码 + 30 只 92，仍对不上）。可行路径是**用同花顺行业成分股补齐**（`HITHINK_FINANCE_*`，`X-api-key` 头）：

- `GET /api/a-share-index/catalog/ths-index-list?tag=industry` → **320 条**（`881xxx.TI` 90 个 + `884xxx.TI` 230 个），字段仅 `thscode`/`name`，一次全量无分页。
- `GET /api/a-share-index/constituents/ths-stock-list?thscode=881121.TI` → 成分股 `item[].thscode/ticker/name`。
- **只用 881 的 90 个行业就 100% 覆盖全市场**。884 是 881 的**子集**（884 独有 = 0），无需拉。
- **同花顺 881 与开盘啦 881 是同一套分类**：共同 90 个代码名称逐字一致；开盘啦 104 = 这 90 个 + **14 个旧代码**（881104、881106、881110、881111、881113、881119、**881120**、881127、881147、881150、881154、881161、**881163**、881176），同花顺没有这 14 个。开盘啦的行业**重叠**正来自这 14 个旧代码，而同花顺的 90 个行业**完全互斥**（每只股票恰好属 1 个行业）。
- **同花顺每个行业的成分股都是开盘啦的严格超集**：逐行业比对「仅开盘啦有」**恒为 0**。所以补北交所可以只做**增量合并**，不必推翻开盘啦的 104 个行业。

**四个必须知道的限制**：

1. **反查接口不存在**：`/api/a-share/stock-basics`、`/api/a-share/ths-index-membership` 返回 **HTTP 404 Route not found**。没有"输入股票→输出行业"的接口，只能靠正向成分股**全量倒排**。
2. **不能批量传 thscode**：逗号形式报 `code=1002` / `code=1001`；`limit`/`offset` 传了无效。必须逐个行业一次请求。
3. **成分股接口无日期参数**：多传 `date`/`trade_date` 返回完全相同的结果 → **只有"当前"成分快照，不可回溯历史交易日**。回补历史日只能拿"今天"的归属去填，语义上是近似（行业归属本身变动很慢，实践可接受）。
4. **`/api/meta/tickers/list` 的 `exchange` 参数无效**：传 `exchange=BJ` 仍返回全市场 —— 不要指望用它筛北交所。同花顺侧 `920xxx` 总数与本地 `core_stock` 一致。

### 落地实现（保留开盘啦 104 个行业，只补成员）

- `core/integrations/hithink/contracts.py` —— `HithinkIndustryIndex(thscode, industry_code, industry_name)`。
- `core/integrations/hithink/mappers.py` —— `map_industry_index()`（只接受 `.TI` 后缀，否则 `HithinkPayloadError`）、`map_industry_constituent()`。
- `core/integrations/hithink/client.py` —— `list_industry_indices()`（`tag=industry`）、`list_industry_constituents(thscode)`（拒绝逗号）。
- `core/services/industry_backfill.py` —— `backfill_missing_industry_stocks(records, *, client=None)`。
- `core/services/sync_industries.py` —— 在开盘啦收完之后、写库之前调用补全；`IndustrySnapshotSyncResult` 加 `backfilled_stock_count`。
- `core/management/commands/sync_kaipanla_industry_snapshot.py` —— 成功消息追加 `Backfilled N stock assignments from Hithink.`
- `backend/tests/test_source_policy.py` —— 把两个新端点登记进 `HITHINK_ENDPOINTS`（**这是刻意的审批守卫：新增同花顺端点必须同步登记，否则 `test_hithink_client_uses_only_approved_...` 失败**）。

**配置**：`.env` / `.env.example` 的 `HITHINK_INDUSTRY_BACKFILL_ENABLED`（默认 `1`）。设 `0` 时补全整段跳过、命令不碰同花顺。**补全失败会整体失败**（不静默退回"北交所无归属"）；同花顺挂了就把它设 0 再跑。

**语义**：

- **只增不删**。开盘啦的成员是权威，同花顺只填它没有的。
- **只补同花顺也有的那 90 个代码**。884xxx 跳过（是 881 的子集，补进去只会制造重叠）；开盘啦多出的 14 个旧代码没有同花顺对应，跳过 —— 实测这 14 个行业里 **0 只北交所成员**。
- 补进来的代码**必须存在于本地 `core_stock`**，否则是永远匹配不上日行情的死数据。
- 每只北交所股票**恰好归属 1 个行业**。

**测试**：`core/tests/test_industry_backfill.py`（8 例：只补缺的、忽略本地不认识的代码、不删开盘啦成员、跳过同花顺没有的代码、不动 CHILD、开关可关、上游异常向上抛、同一只被两个行业补到时只计一次）；`core/tests/test_hithink_adapter.py` 的客户端用例；`test_sync_industries_commands.py` 里既有用例在 `setUp` 把补全函数 patch 成空实现（**否则那些用例会去打真实上游**），另有 1 例端到端接线。

## 盘中高频刷新

### 5 分钟板块资金流

- 链路：`SNAPSHOT_INTERVAL_MINUTES=5`、`trading_slots_for_day()` 一天 **50 个槽（09:30…15:00）**、`resolve_snapshot_slot()` 按运行时刻归槽、`fetch_kaipanla_sector_fund_flow` 默认**只在交易日的连续竞价时段采集**（闸门是 `core/services/calendar.is_trading_session()`；时段常量 `TRADING_SESSIONS` 也在 `core/services/calendar.py`，`kaipanla.services.intraday` 从那里 import，不再自己定义一份）、`read_intraday` 返回 `time_points`+`series`。
- 调度一律走**系统 crontab**（完整块见 `docs/ops/deployment.md` §6）；仓库里没有 APScheduler / celery 之类的进程内调度器。

### 通用闸门：`latest_eligible_trading_day()` 的 15:00 断点

**盘中把当天数据写进库，页面默认入口仍然显示前一天。** `latest_complete_stock_price_date()` 用 `latest_eligible_trading_day()` 当上限，而后者在"当天 < 15:00"时**主动退一天**。三个盘后模块的 `_resolve_read_date()` 都走这条路。

**绕过方式只有显式 `?date=`**：`requested_explicitly = trade_date is not None`（服务层）与 `'date' in request.GET`（视图层）成对判定，显式日期不退回、直接读当天并在缺产物时 `_local_generate`。**两边语义必须一致，改一处要同时改。**

### 全市场行情快照端点是盘中刷新的唯一可行通道

`get_historical_prices` 是**一只股票一次请求**；`/api/a-share/prices/snapshot` 则是**全市场分页**（省略 `thscodes`，用 `limit`/`offset`），`limit=1000` 实测 **6 页 / 全部股票 / 1.7s**，字段 `last_price`/`open_price`/`high_price`/`low_price`/`prev_price`/`volume`/`turnover`/`price_change_ratio_pct` 正好够拼 `MarketPrice`。接入点是 `HithinkClient.list_market_quotes` + `HITHINK_ENDPOINTS` 白名单登记（**漏登记会让 `test_hithink_client_uses_only_approved_...` 失败**）。

**三个语义差异（用快照写当天日行情前必须处理）**：

1. **`turnover`/`volume` 低位被舍入**（如 979990554.2 → 979990550）：相对误差 ~1e-7。日期当天的 `close/open/high/low` 与 `adjust=forward` 历史接口**逐只完全一致**。
2. **除权除息日 `prev_price`/`price_change_ratio_pct` 是原始值**，不是除权参考价。**管线口径是对的，快照那天会错几只**，收盘后历史同步会纠正。
3. **停牌股返回 `last_price=null` + `volume/turnover=0`**，必须映射成 `has_valid_trade=False` 且不写价；**新股/复牌本地 `pre_close` 为 None 时涨跌幅应为 None**。历史接口还支持 `adjust=none`（`raw`/`bfq` 报 `1002`）。

### 个股日行情的三段式链路

**盘中快照是唯一的日常写入路径**：

1. **每周日 04:00 全量校正**：`init_stock_daily_prices --years 1` → `initialize_stock_daily_prices()`（`backend/core/services/sync_daily_prices.py`），逐只 `/api/a-share/prices/historical`，窗口 = `_one_year_before(latest_eligible_trading_day())` 起到今天。由 crontab 的周日那一行承载（`0 4 * * 7`），成功后连锁重建三个 `build_*`。**它不是一次性命令**（重跑只写差异行），而且是**唯一能补历史某一天、唯一能补复牌股昨收（`_previous_closes` 只看紧邻上一交易日）的手段**。**绝不能改成每日，也绝不能进 Web 路径**（全量级请求，五千余次）。
2. **交易日盘中每 30 分钟**：`refresh_intraday_quotes` → 全市场快照（**约 6 个请求**，分页）。crontab 表达式 **`0,30 9-15 * * 1-5` 一条**（时段内 10 个有效刻度，含收盘那一刻 15:00）。**这一轮不只是刷新行情**：链上取数与三个 `build_*` 用 `&&` 串联，刷新失败则三个模块不重建。注意 `&&` 分辨不了「跳过」与「成功」—— 被闸门跳过时退出码也是 0，三个 `build_*` 会照常跑一遍本地重算（幂等、毫秒级）。
3. **交易日 15:35 盘后定稿**：`refresh_intraday_quotes --latest`，crontab 表达式 `35 15 * * 1-5`。**为什么是 15:35 而不是刚收盘**：北交所盘后固定价格交易到 15:30，15:00 那一轮快照不是结算终值。

**`adjust=forward`（前复权）会重算全部历史**：新的分红/送转事件会让整段历史价格变化 ⇒ 隔一段时间重跑 `init_stock_daily_prices` 时发现**大量历史行与上游不同是正常的**，不代表之前导入错了。这也正是"无差异不写入"必须存在的原因。

**闸门**：`refresh_intraday_quotes` 有两道 —— ① `not is_trading_day(today)` **无条件跳过**（连 `--latest` 也不放行：快照端点没有日期参数，休市日跑它只会把上一交易日的收盘态冒充成今天），② `not --latest and not is_trading_session(now)` 跳过。两处都 `log_command_progress(action='skipped', reason=...)` 并以**退出码 0** 结束。**命令刻意没有 `--date`**：业务日期恒为 `_now().date()`，要补过去的日期只能重跑 `init_stock_daily_prices`。

**三个 `build_*` 的 `--date` 是可选的**（`default=None` → `core.services.market_data.resolve_business_date()` → `latest_complete_stock_price_date()`），与页面默认锚点同一个。好处是调度器不必在 shell 里推算交易日 —— **周日跑 `init` 时那天是上一个交易日（周五），不是周日**。

**"只装 snapshot 那条就够了"要分两层看**：(a) 行数层面**够** —— 收盘后快照覆盖 100%，"快照漏停牌股"在收盘后不成立；停牌股也照样有行（价格 NULL + `has_valid_trade=False`）。(b) 精度层面**不够** —— 快照的 `turnover` 有末位浮点噪声、少数北交所标的量额与历史口径有真差异（外部行情吻合的是**快照**），复牌股 `pre_close`/`change_percent` 快照路径给不出。这些由每周日的 `init` 兜住，**最多滞后一周**。

### 盘中链路的实现要点

- **命令**：`refresh_intraday_quotes [--latest] [--dry-run]` → `sync_daily_prices.refresh_intraday_daily_prices()`。分页抓全市场快照（50 页防呆），只保留本地活跃股票；**快照里没有的股票跳过而不是清零**（"没收到"≠"停牌"；断掉的 `pre_close` 链条与停牌缺口由每周日的 `init_stock_daily_prices` 补齐）。复用 `_upsert`/`_split_changed_records`；**无变化不写库**。
- **口径**：`pre_close`/`change_percent` 一律用库内上一交易日收盘重算（`_previous_closes` 按整天查，不用 `stock_id__in` —— 5571 个绑定参数会撞 SQLite 上限）；停牌落 `has_valid_trade=False` 且价格/成交量全 `None`；本地无前收则涨跌幅 `None`。闸门 `INTRADAY_QUOTE_MIN_COVERAGE_RATIO`（0.95）与 `INTRADAY_QUOTE_PAGE_SIZE`（1000）在 `.env`，覆盖率不足整体失败、不标 complete。
- **日期闸门**：`latest_complete_stock_price_date()` 放宽上限 —— `eligible_day < today` 且**当天已有公共行情行**（`has_stock_prices(today)`，`exists()` 口径）时提到 today，否则不变。**不动 `latest_eligible_trading_day()`**（"是否已收盘"的语义归盘后定稿）。
- **例外：板块资金流不使用这条日期闸门**（`kaipanla/services/read_path.py::_resolve_default_version`）：它锚定**本模块自己的最新已存快照日**。时钟只用来回答"该有快照的最新交易日"（`_latest_expected_snapshot_date()`：交易日 **09:30** 起为当天，开盘前/休市日为最近一个已收盘交易日，**不是** 15:00 口径）。
- **调度**：crontab 四条采集行（`*/5 9-15` 资金流、`0,30 9-15` 行情 + 重建、`35 15` 定稿 + 重建、`0 4 * * 7` 全量校正 + 重建），完整块与逐条理由见 `docs/ops/deployment.md` §6。**表达式只写「周一到周五 + 交易钟点」粗范围，不复刻 09:30-11:30 / 13:00-15:00 边界** —— 那是会随 `TRADING_SESSIONS` 调整而悄悄失准的第二份定义；时段外的刻度由命令的闸门跳掉（退出码 0），代价是资金流每天 34 个、行情每天 4 个空跑刻度。日志在 `backend/logs/`（`kaipanla.log` / `daily-prices.log` / `stock-master.log` / `industry.log`）。
- **坑 1（本机无法自动安装调度）**：`/usr/bin/crontab` 读写都报 `Operation not permitted`（macOS TCC 需完全磁盘访问）。**必须让用户自己在 Terminal.app 里 `crontab -e` 粘贴 `docs/ops/deployment.md` §6 的块**，再用 `crontab -l` 确认。
- **坑 2（前端取数 hook）**：`useResource` 里 `apiClient` 必须经 ref 持有、**不能进 effect 依赖数组** —— 调用方每次渲染新建 client 对象会让 effect 无限重跑，测试这样写直接把 node 跑到 OOM（`Reached heap limit`）。测试也要在同一作用域建一次 client 实例。
- **已知代价**：盘中每 30 分钟刷一轮，当天行情行会被反复 upsert（**不累积行** —— 同一天就是那 5,573 行，且无变化时不写）。

### 分时图横轴：恒为完整交易时段

- `kaipanla.services.intraday.query_intraday` 的 `time_points` **永远是一整天的 50 个五分钟槽**（09:30–11:30 / 13:00–15:00），**不按"已到达的时点"截断**。
- 当天没走完由**每条曲线**表达：`_build_series` 里 `collected_axis = time_axis[: index(source_time) + 1]`，`series[].data` 只到最后一个已采集的时点，其后既不补零也不复制末值。
- 因此 **`query_intraday` 不接受 `now` 参数**：payload 是（业务日期 + 该日已落库快照）的纯函数，查询时刻不进 payload，同一批快照的缓存结果盘中不会被时钟改写。
- 一条快照都没有的交易日仍返回空 `time_points`/`series`（空态，不返回"只有刻度的空图"）。
- 刻度密度与显示文本是**前端的渲染决策**，不回写契约（细则见 `frontend-conventions.md`）。

### 交易时段闸门：**边界按整分钟判定**

- **铁律**：`core/services/calendar.py::is_trading_session` 的比较单位是**整分钟**（`_minute_of_day(hh*60+mm)`），四个边界整点（09:30 / 11:30 / 13:00 / 15:00）**所在的那一分钟**都算盘中：`11:30:59` 是盘中，`11:31:00` 起是盘外。`TRADING_SESSIONS` 的 `end` 仍是"结束的那个钟点"（`time(11,30)`），**不要**把它改成 `11:31`/`15:01` 来"放宽"——那会让 `trading_slots_for_day` 的语义一起被污染。
- **为什么必须这样**：调度是"到点拉起新进程"，cron 在整点触发、Django 读到时钟时已晚一秒多。用闭区间比 `time` 会让 `11:30` 那一轮**每天**被闸门拒掉，库里永远缺 11:30 槽（页面分时曲线末端停在 11:25）。**归槽本身没问题**：`resolve_snapshot_slot(11:30:01)` 返回的就是 `11:30`，挡路的只有闸门。
- 09:30/09:35 缺失与闸门无关：**先查 `sysctl -n kern.boottime`**（机器没开机时那条 cron 根本没机会跑）。
- 完整排查手法（含 `/usr/bin/log show` 的 zsh 内建与宽窗口坑）见技能 `backend-dataset-diagnosis` §4.3。

## 数据库迁移：必须逐库执行

**标准姿势是逐库跑**：

```bash
python manage.py migrate --database=default
python manage.py migrate --database=kaipanla
python manage.py migrate --database=stock_moves
python manage.py migrate --database=sector_momentum
python manage.py migrate --database=hundred_day
```

**裸 `migrate`（不带 `--database`）只作用于 `default`，而且它会撒谎**：`db_router.allow_migrate` 让业务 app 的 operation 在 `default` 上变成 no-op，可 Django **照样打印 `Applying stock_moves.0005_... OK`**，并把记录写进 `default` 库的 `django_migrations`。结果是"迁移全绿"但业务库里一个字段都没动 —— 排查时要直接 `PRAGMA table_info(<业务库表>)` 看列名，**别看迁移命令的输出**。模块库因此会**停在它最后一次 migrate 的时刻**（页面照常能读，只是结构是旧的）；查漂移用 `manage.py showmigrations --database=<alias>` 看 `[ ]` 行。

**第二个坑：Django 在 SQLite 上把 `RenameField` 编译成 `-- (no-op)`**。字段改名**必须**这样写，否则列名不动：

```python
migrations.SeparateDatabaseAndState(
    database_operations=[
        migrations.RunSQL(
            sql='ALTER TABLE t RENAME COLUMN old TO new;',
            reverse_sql='ALTER TABLE t RENAME COLUMN new TO old;',
        ),
    ],
    state_operations=[migrations.RenameField(model_name=..., old_name=..., new_name=...)],
)
```

SQLite 3.25+ 的 `RENAME COLUMN` 原地改名、**数据完整保留**。反之，若让 `makemigrations` 自动检测，非交互模式下会把改名判成 remove + add —— **直接删掉整列数据**。

**`sqlmigrate` 也不能用来判断业务库会发生什么**：它默认连 `default`，对业务 app 的 operation 一律显示 `(no-op)`（同样因为 router）。要验证只能真跑 + `PRAGMA` 复查。

**`makemigrations` 必须加 `--noinput`**：遇到"新增非空字段没有默认值"会交互式提问，非交互环境下退出码是 **137（SIGTERM）** 而不是报错。

## 应用日志体系（改日志前先读这一节）

- **两路日志，都由环境变量控制、改完重启即生效**：`DATA_COMMAND_LOG_LEVEL`（管理命令 + 进度行）、`DJANGO_LOG_LEVEL`（`core` + 四业务模块 + Web 访问日志）、`DJANGO_LOG_FORMAT`（`plain`=单行 `key=value` / `json`）、`DJANGO_REQUEST_LOG_SLOW_MS`（默认 1000）。用户文档在 `docs/ops/manage-commands.md` §3.7 与 `docs/ops/deployment.md` §2.1。
- **`settings.LOGGING` 的关键前提**：`django.utils.log.configure_logging` 是**先 `dictConfig(DEFAULT_LOGGING)` 再应用 `settings.LOGGING`**，所以**重定义 `console` handler 就能让 `django.request` / `django.server` 一并走自定义格式**；`disable_existing_loggers` 必须 `False`，否则这两个 logger 被静音。改 `LOGGING` 前先复读 `django/utils/log.py`，别凭记忆。
- **`core/logging.py` 的三个入口**：`log_command_event`（命令生命周期）、`log_command_progress`（进度行）、`log_event(logger, event, *, level, exc_info, **fields)`（业务事件）。`log_event` 渲染单行 `key=value`，并把 `event`/`event_fields` 放进 `extra` 供 `JsonFormatter` 提升为顶层键。
- **`LogRecord` 保留属性**：`extra` 覆盖 `module`/`name`/`message` 等既有属性会抛 `KeyError: "Attempt to overwrite 'module' in LogRecord"`。`_RESERVED_RECORD_KEYS` 先过滤，这类字段留在 message 里、不进 `event_fields`。
- **`RequestContextFilter` 是安全网**：它给**每条**记录（含 Django 自身与第三方）兜底注入 `request_id`，格式串里的 `%(request_id)s` 才能对任意记录安全求值。请求上下文用 `request_logging_context`（`ContextVar`）承载，不逐层透传。
- **请求关联**：`RequestLoggingMiddleware`（`core/middleware.py`）从入站 `X-Request-ID` 取 id，经 **`^[A-Za-z0-9._-]{1,64}$` 白名单校验**（防日志伪造），并回写响应头。**事件分级口径**：quiet 路径（`/static/`、`/favicon.ico`、`/api/core/health/`）→ DEBUG；≥ `REQUEST_LOG_SLOW_MS` → WARNING `http_request_slow`；异常逃出中间件 → ERROR `http_request_failed` 后 `raise`；其余 → INFO `http_request`。**4xx 不升级**（严重级别由 `django.request` 负责，避免重复计数）。
- **读路径事件（排查"页面为什么慢/为什么是旧数据"主要看这几个）**：`read_generated`（本次请求现算）+ `read_served`（DEBUG）/ `read_stale_fallback`（WARNING，退回旧数据，页面同时显示"正在展示旧数据"）/ `read_unavailable`（WARNING 后 raise，API 多返回 404/202）/ `read_preparing`（WARNING，**仅 kaipanla**：当天还没采集到且仍在采集窗口内，返回 202）。三个盘后模块的 `read_path.py` 统一是「`read_*` 薄包装 + `_read_*` 原逻辑」结构，**加日志只动包装层，不要往业务逻辑里塞**。
- **上游日志口径**：重试记 WARNING（`upstream_retry` / `page_retry`）、放弃记 ERROR（`upstream_failed` / `page_failed`）、**成功只记 DEBUG** —— 一次同步几千次调用，INFO 会把日志淹掉。
- **采集失败的账目事件 `kaipanla_collection_incomplete`（WARNING）**：字段 `expected_record_count` / `collected_record_count` / `missing_record_count` / `invalid_row_count` / `page_progress` / `failed_page_offsets` / `failure_kind` / `detail`，由 `fetch_kaipanla_sector_fund_flow.py::_log_incomplete_collection` 发出。**采集不全 = 一行都不落库**，所以库里不会留下任何"半份"痕迹。
- **`kaipanla` 没有运行表、也不写版本表**：写行即发布。查这个模块"有没有数据"要用 `queries.latest_trade_date()`。
- **脱敏与防注入是硬要求**：所有字段先过 `redact_sensitive_text()`，再折叠换行（防日志注入）、单字段截断 500 字符。**登录失败只记 username、绝不记密码**。`extra` 里的 `JsonFormatter` 时间用 `timezone.localtime` 输出本地 ISO。新增日志一律走 `log_event`，不要裸 `logger.info(f'...')`。
- 单测在 `backend/core/tests/test_request_logging.py`。

## 命令契约、日志与性能

- `BaseDataCommand`（`core/management/base.py`）用 `dataset_lock` + `log_command_event` 输出生命周期事件 `data_command_started`/`finished`/`failed`/`locked`；子类实现 `run_data_sync`/`format_success_message`/`get_business_date`。
- **命令进度日志**：长耗时命令在 started/finished 之间持续输出事件名 **`data_command_progress`**（字段 `stage` + `processed`/`total`/`percent`/`eta_seconds`，默认**每 30 秒最多一行**，阶段首尾各强制一行）。实现是 `core.logging` 的 `command_logging_context`（`ContextVar` 绑批次身份）+ `ProgressReporter`；`BaseDataCommand.handle` 负责绑定，**服务层可直接调 `log_command_progress(stage, **details)`，不必透传 module_id/batch_id**；无绑定上下文时返回 `False` 且不输出。判断"命令是否卡住"看 `processed` 是否增长。
- **`backend/env.py` 已做配置缓存**（`_PARSE_CACHE`，每 `ENV_CACHE_TTL_SECONDS=5.0` 秒比对一次文件指纹；`get_setting` 先查 `os.environ`，命中就完全不碰文件）。**改这个文件前先读一遍**：若写成 `os.environ.get(name, _file_values().get(name, default))`，每次取配置都会重读整个 `.env`（一次全量初始化 = 186 次读取，占掉 99% 运行时长）。新增配置读取复用 `get_setting` 系列，不要自己 `Path('.env').read_text()`。脱敏见 `core/logging.py` 的 `redact_sensitive_text()`。
- **`get_setting(name, default)` 不把空串当未配置**：`os.environ` 命中空串就返回空串；要"留空即回落默认值"必须自己 `.strip() or default`。
- 命令类测试要**冻结时间**（`patch('django.utils.timezone.now', return_value=...)`），否则槽位判定会跟真实运行日期漂移；`--dry-run` 也会先算槽位。**交易日不需要建任何行**：测试要么挑真实交易日，要么 `patch('core.services.calendar.trading_days_between', ...)` / `patch('core.services.calendar.is_trading_day', ...)` 把窗口收窄到 fixture 的几天 —— 例如 `init_stock_daily_prices --years 1` 会算出真实的 ~242 天窗口，`_validate_market_coverage` 会要求每一天都有 bar，必须 patch 掉。
- **性能基线**：`get_complete_market_snapshot` ≈0.55s；百日最重 —— `load_hundred_day_source_data` ≈2.8–4.4s（110 万行必须用 `values_list` 批量取值，`select_related` 逐对象要 14.7s）+ `build_hundred_day_analysis` ≈0.32–0.4s，单日按需生成合计 ≈3.5–5s。**`hundred_day/services/flags.py` 的 `compute_high_low_flags` 用双单调队列做滑窗极值**，语义由 `tests/test_flags.py` 的"朴素窗口差分测试"锁住（改它必须让该差分测试通过）。`build_stock_move_analysis` ≈0s、`build_sector_momentum_analysis` ≈0.02s。

## 测试与回归清理

- **判回归前先清两样**：`backend/data/locks/*.lock`（`dataset_lock` 残留会让 `call_command` 用例集体报 `DatasetLocked`/`FileExistsError`；锁名 = `sha256('module:dataset')`，可反查归属）与 `backend/cache/`（陈旧条目会让期望 `source='database'` 的用例拿到 `'cache'`）。只认"清完之后的第一次全量运行"。要区分回归与既有失败，用 `git worktree` 建基线树对比（注意 `.env` 在**仓库根**）。
- **跑全量后端测试要加 `CODEBUDDY_SAFE_DELETE_ENABLED=0`**：CLI 的 `sitecustomize.py` safe-delete shim 会拦截 `Path.unlink`（`dataset_lock` 退出时删锁即触发），单个 turn 删除数超过阈值就 `SystemExit(1)`，表现为几十个**无关**用例集体 ERROR。跑完用 `ls backend/data/locks | wc -l` 确认 0 泄漏。
- **必须在 `backend/` 目录下跑 `manage.py test`**：从仓库根跑会 `Found 0 test(s)` + `NO TESTS RAN`，且**退出码仍是 0** —— 别当成"全过"。测试发现以 `cwd` 为起点，仓库根的 `tests/` 里没有 Django 用例。
- **当前基线**：后端全量约 440 个用例，唯一失败是 `backend/backend/tests/test_security_settings.py::test_runtime_security_settings_are_safe_by_default` —— 本机 `.env` 是生产口径（`DJANGO_DEBUG=false` 且 `DJANGO_SECRET_KEY` 仍是 `.env.example` 的占位符）时它真的执行那组断言并失败。**这是 `.env` 口径问题，与代码无关**；把本机 `.env` 改成调试口径（`DJANGO_DEBUG=true`）它会 `skipTest`。判回归时先确认失败集合只有这一条。**用例总数会随迭代增长，别把具体数字当固定值。**
- 同时跑真实命令与测试会**假连锁**：锁是文件系统级的（`backend/data/locks/*.lock`），不随测试库隔离。特征 = 失败只落在几个不相干的 `call_command` 用例、单独跑那些模块完全正常、套件总耗时明显变长。对策 = 等真实命令结束再跑。

## 读路径锚点、缓存身份与分组顺序

- **默认入口锚点分两种，不要混用**：三个盘后模块用 `latest_complete_stock_price_date()`（最新完整**公共日行情**日）；**板块资金流是唯一例外** —— `kaipanla/services/read_path.py::_resolve_default_date` 锚定**本模块自己最新的已存快照日**（`queries.latest_trade_date()`），与公共日行情日期无关。时钟只决定"该有快照的最新交易日"：`_latest_expected_snapshot_date()` 在交易日 **09:30** 起算当天，开盘前与休市日为最近一个已收盘交易日（**刻意不用** `latest_eligible_trading_day()` 的 15:00 口径）。快照已覆盖该日 → 直接服务、`stale=False`；落后时按时间分岔：**当天仍在采集窗口内（`_today_is_still_collecting()`，交易日收盘前）→ 202 `DATA_PREPARING`**，否则 → 最近一次快照 + `stale=True`。**全程不访问上游。** AC-FLOW-010 锁住这个语义。
- **缓存身份**：`_identity(trade_date, newest_slot)` → `kaipanla:<date>T<HH:MM>`，即当天**最新采集槽**。新槽落库键就变，因此缓存不可能比它对应的行活得更久。
- **`data_updated_at`：面向前端的"数据时刻"**：`ReadResult`（core 与 kaipanla 各一份）都有这个字段，`handlers.success()` 把它塞进外壳，前端 `RefreshStamp` 显示成「更新于 HH:MM」。取值口径：**三个盘后模块 = 所服务行的 `published_at`**；**kaipanla = 当天最新采集槽那批行的 `created_at`**（`queries.latest_snapshot()` 一次查询同时返回槽与写入时刻）。三条要点：① 它**永远不是** `generated_at`（那个每次请求都前进，含缓存命中）；② **缓存命中分支也必须带上**（缓存只存载荷，信封每次重建）；③ **它同时是文件缓存的缓存身份**（`cache_identity = result.published_at.isoformat()`），所以三个模块的 writer 每次构建都显式盖章、且写入是"先删该日全部行再整批重建"——**重跑一定让它前进**，否则重建后最长 `FILE_CACHE_TTL_SECONDS`（300s）仍发上一版报文。序列化在 `core/api/responses.py::_iso`（aware datetime 先 `localtime` 再 `isoformat`，带偏移量）。
- **响应外壳的 `source` 只有三个字面量**：`cache` / `database` / `computed`（**没有** `generated` / `remote`）。
- **`HundredDayStockFlag` 自带 `change_percent` / `turnover`，不得读时回查 `core`**：这两个值若靠回查公共行情补，读路径就依赖了"事后会变的输入"；结果是按天发布的快照，必须自带。
- **`stock_moves` 有五个分组**：上证/深证涨跌四组 + `bse`（北交所，同阈值但单独成组，无数据不渲染）。`stock_codes` 按**页面分组顺序**返回（非字典序），前端 `.join(',')` 得到与表格一致的复制串 —— 改这里必须同步看 `stock_moves/tests/test_api.py` 的顺序断言。
- **crontab 只有一份副本**：完整块在 `docs/ops/deployment.md` §6（四条采集行 + 两条参考数据行），命令手册 §9 只讲命令侧的调度约束、不重复块本身。**别把同一个采集槽排两遍** —— 上游请求数会平白翻倍。
