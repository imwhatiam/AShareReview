# 后端数据管道：交易日、上游、命令与性能（专题）

从 `.workbuddy/memory/MEMORY.md` 拆出，按需读取。**故障排查流程**（"命令成功但页面没数据"）见 `.workbuddy/skills/backend-dataset-diagnosis/SKILL.md`。

## 交易日、上游与快照

- **快照时刻只有一处判定：`kaipanla.services.intraday.resolve_snapshot_slot(运行时刻)`**（管理命令、`--latest`、Web 补齐三处共用）。按运行时刻（**不用上游 `Time` 字段**）给唯一合法槽：盘中向前回退到所在 5 分钟槽（09:33→09:30）、午休回退 11:30、**盘后一律 15:00**、**非交易日与开盘前落到最近一个交易日的 15:00**（覆盖之，不写当天假收盘）。旧 `last_reached_slot()` 已删。
- **`intraday.is_trading_day()` 两层判定**：① 周末直接不是交易日（也覆盖"调休上班的周末"）；② 工作日的法定节假日由 **`chinese-calendar`**（已进 `backend/requirements.txt`）判定，因此不再依赖同花顺日历是否已同步到当天。该库**按年内置数据**，抛 `NotImplementedError` 时才退回同花顺 `TradingDay`；**每年放假安排公布后要升级该包**。`_can_attempt_repair()` 还要求该日是交易日，故周六/节假日走 404 而非 202；`_repair_snapshot_time()` 在槽位不属于请求日时返回 None 并**先于上游请求**短路。
- **上游日期参数必须落在交易日**：开盘啦**历史**端点（`KAIPANLA_INDUSTRY_API_URL` → `apphis`，与实时资金流 `apphwshhq` 是两条独立 URL）只服务交易日，传周末/节假日回 `errcode 1020 参数出错`。行业快照 `Date` 默认值由 `core.services.calendar.latest_trading_date()` 解析（同花顺 `TradingDay` 日历优先，落后/为空时用 `chinese-calendar` 回退），**不要写 `timezone.localdate()`**；它和 `latest_eligible_trading_day()` 语义不同（后者问"当天收盘了没有"，会退一天）。上游非 0 `errcode` 会把 `errcode`/`errmsg` 带进异常消息。
- **开盘啦两个端点的分页 `st` 上限完全不同**：成分股 `ZhiShuStockList_W8` **无实际上限**（`.env` 用 `KAIPANLA_INDUSTRY_STOCK_PAGE_SIZE=300`，已对 2291 只的板块复验逐只一致）；板块列表 `RealRankingInfo` 有**约 70 的隐性上限，`st≥75` 静默返回空列表**（客户端会当"分页结束"→板块被静默截断），故 `KAIPANLA_INDUSTRY_PARENT_PAGE_SIZE` **必须保持 30**。提成分股分页只压得动分页请求，**每个行业至少一次请求**的下限压不掉。全量行业快照实测约 4 分钟（104 个 881 行业），必须后台跑。
- kaipanla 资金流 `main_net_inflow` 单位是**元**，读路径 `/1e8` 再 `round(...,4)`。测试数据用亿级（`Decimal('200000000')`）；写 `Decimal('20')` 会被四舍五入成 0，正负榜双双过滤掉，表现为"series 恒为空"的假 bug。

### 板块代码族：`ZSType` 才是选族的开关（2026-09-12 实测）

`RealRankingInfo`（`c=ZhiShuRanking`）除 `Type` 外还有一个**大写 `ZSType`**，它是选"取哪一族板块"的开关，项目此前一直只用 `ZSType=7`：

| `ZSType` | 返回 | 条数 | 顶层 `list_son`/`list_soninfo` |
|---|---|---|---|
| 4 | **881xxx 行业**（元件 / 通信设备 / 半导体 / 银行…） | 104 | 空（扁平，无层级） |
| 5 | 885xxx / 886xxx 概念 | 499 | 空 |
| 6 / 8 | 801xxx **地域**（湖北省 / 北京市…） | 40 | — |
| 7 | 801xxx / 803xxx 开盘啦自编概念题材 | 270 | **有**（PCB / 光模块 / 覆铜板…） |
| 1/2/3/9–15 | 空 | 0 | — |

- **`Type` 不是族开关，是榜单口径**；而且 `Type=12/13/14` 会**越过 `ZSType`** 直接返回 80xxxx。要 88 行业必须固定 `Type=1`。
- **881 族是扁平结构（无层级）**：同代码族下不存在更细的一层。成分股照常可取：`ZhiShuStockList_W8` 需 `Type=6`（`Type=0` 返回空），`Index` 分页正常，`st` 直到 1000 都不截断（881120 在 `st`=30/60/100/300/1000 下逐只一致，375 只）。
- **104 个 881 代码与名称在 09-07~09-11 五个交易日完全一致**（0 增减、0 改名）。**`Count` 字段不可信**（有时是总条数、有时是当页条数，末页给 14）—— 客户端靠"行数 < page_size"判终止是对的，别改用 `Count`。
- **881 各行业之间有重叠**，不是互斥划分：881120 电力设备 375 只**包含** 881279 光伏设备的 59/70 只；104 个行业成分股计数合计 6361 > A 股总数。用它做行业归属前必须去重。
- **同一 88 行业在两条端点上成分股不同**：实时 `apphwshhq` 带北交所，历史 `apphis` **不含北交所**（881120 375→351，剔掉的 24 只全是 43/83/87 开头）。而 80xxx 概念走 `apphis` 是**带 920xxx 北交所的** —— "北交所缺失"只出现在 88 族 + 历史端点这个组合上。
- **零代码改动即可切到 88 行业**：只把 `.env` 的 `KAIPANLA_INDUSTRY_PARENT_ZS_TYPE` 由 `7` 改成 `4`（`sync_industries._collect_industry_snapshot` 现在直接按行业代码取成分股，无回退分支），实测得到 104 条行业记录、881270 元件 60 只、881120 电力设备 351 只（apphis）。**代价**：88 行业与 801xxx 概念共用同一 dataset `industry_snapshot` 和同一张表，切换会覆盖既有快照，二者不能并存。

### 88 行业的板块资金流：能取，且零代码改动（2026-09-12 实测）

板块资金流与行业列表**用的是同一个 action** `RealRankingInfo`（`c=ZhiShuRanking`），族开关同样是 `ZSType`。所以 `.env` 的 `KAIPANLA_FLOW_ZS_TYPE` 由 `7` 改成 `4` 即可取 881 行业资金流，**不需要动代码**（`KAIPANLA_FLOW_TYPE` 必须保持 `1`）。

- 端到端实测（`KAIPANLA_FLOW_ZS_TYPE=4` 覆盖环境变量，`KaipanlaSectorFundFlowFetcher().fetch()`）：`is_complete=True`、**104 行 / 2 页**、`source_trade_date=2026-09-11`、耗时 0.8s。
- 行结构与 80 族**完全一致（19 列）**，`parse_sector_row` 104/104 全部解析成功、无 `None`、主力净流入无一为 0。样例：881129 通信设备 +50.30 亿、881270 元件 +39.51 亿、881113 有色冶炼加工 −65.23 亿。
- `Count=104` 在 `Index=0/80` 两页都稳定（`Index=160` 才空），所以 fetcher 的 `ceil(Count/page_size)=2` 判定正确、`行数 < page_size` 的末页例外也命中。**注意这跟上一节"末页 Count 给 14"的观察不同**：那是在 `st=30` 的行业列表上见到的，`st=80` 的资金流没复现，不能一概而论。
- **`item[14..16]` 是族间唯一字段差异**：88 族 **104/104 恒为 0**，80 族有值（175/262/262，即"机构增仓 / 2026 PE / 2027 PE"）。这三列 `parser` 不读，不影响落库与页面，只是这两列在行业上不可用。
- **历史回补窗口只有 3 个交易日**（端点的滚动窗口，不是 88 族特有问题）：实时 `apphwshhq` + `Date` 在 09-09/09-10/09-11 都有 104 行且数值确实随日期变化，**09-08 及更早一律 `Count=0`**；80 族在 09-08 同样是 0。
- **`apphis` 历史端点对 88 族资金流完全空**（`errcode=0` 但 `Count=0`，`st`/`Date` 各种组合都试过）；同端点 80 族也不是随时可用（09-11 空、09-08 给 10 行）。**行业列表用的 `KAIPANLA_INDUSTRY_API_URL=apphis` 与资金流用的 `KAIPANLA_API_URL=apphwshhq` 是两条端点，别混用**——88 族在两者上的可用性完全不同。
- 带 `Date` 请求历史时，响应里的 `Day` 仍是**最新交易日**（不随 `Date` 变），而 fetcher 的 `_source_metadata` 正是取 `Day[0]` 当业务日期 → 用 `Date` 回补会把旧数据落在新日期上。项目现网不传 `Date`（靠定时落库），所以不触发。
- **不能与 80 族并存**：单次请求 `ZSType` 单选，且 `kaipanla_sector_fund_flow` 只有一个 dataset。切族会与既有 540 条 801/803 快照（09-09、09-11 各 270 条）**混在同一张表**，`query_intraday_history`（1/5/10/20 日窗口）会把两族按 code 混排，且 88 族只有切换后那几天有数据。要并存必须再加一个 dataset + 独立表。
- 前后端**没有任何板块代码前缀硬编码**（grep `8016/8030/881/startswith('8` 均无命中），切族不会撞上写死的判断。

### 全面切换到 881 行业族的执行记录与已知代价（2026-09-12 已执行）

**配置**（`.env` 与 `.env.example` 同步）：`KAIPANLA_INDUSTRY_PARENT_ZS_TYPE` 7→**4**、`KAIPANLA_FLOW_ZS_TYPE` 7→**4**；`KAIPANLA_FLOW_TYPE` 保持 `1`。其余参数无需改（`PARENT_PAGE_SIZE=30` → 104/30=4 页；`STOCK_PAGE_SIZE=300` → 最大行业 375 只走 2 页；`FLOW_PAGE_SIZE=80` → 104 条走 2 页）。

**改配置必须配套清数据，三个原因**：
- `write_complete_snapshot` 是按 `(sector_code, snapshot_time)` **upsert**，不删旧族 → 旧日的 801/803 行会留在同一张表里混族。
- `core.services.market_data.get_complete_market_snapshot` 取 `IndustrySnapshot.objects.all()` **不按版本过滤**（`industry_level` 字段与父子层级已于 2026-09-12 删除）→ 表里同时有两族行业时，sector_momentum / hundred_day / stock_moves 的板块划分会两族混排。
- `sector_momentum` / `hundred_day` 的产物按 `source_industry_version` 判定，换族后旧产物要么过期要么被当有效。

清理范围（已执行）：`IndustrySnapshot` 812 行 + `DataVersion[industry_snapshot]` 9 条；kaipanla 快照 540 + run 7 + `DataVersion[kaipanla_sector_fund_flow]` 7 条；stock_moves 173/4/7；sector_momentum 60/3/3；hundred_day 807/688/300/3/5；`backend/cache/` 全部文件。**`stock_daily_prices`(727)、`trading_calendar`(3)、`stock_master`(2) 的版本必须保留**，删了要重跑同花顺全量。执行前整库备份在 `backend/data/_backup_before_881_20260912/`（core 281M + 其余四个）。

**执行命令**（`backend/` 下，`manage.py`）：`sync_kaipanla_industry_snapshot`（4m8s，**104 条行业**、业务日 2026-09-11）→ `fetch_kaipanla_sector_fund_flow --latest`（2.4s，104 条，2/2 页；**非交易时段不加 `--latest` 会直接报错**）→ `build_stock_moves --date 2026-09-11`(49 条) / `build_sector_momentum --date 2026-09-11`(20 条) / `build_hundred_day --date 2026-09-11`(331 条)。四个模块的 `read_*` 入口实测均 `stale=False`、`source=database`。

**切换当时的代价：313 只北交所股票无法归入行业**（**2026-09-12 当天已修复**，见下方「同花顺补齐」小节）。`sector_momentum` 的 `unmapped_stock_count` 从旧族的 **5** 涨到 **313**（页面会显示"313 只有效股票未映射到开盘啦板块"）。313 只**全是 920xxx**（当日 5550 只有效股票中）。根因是**上游 881 族对北交所用的是旧代码**，不是端点问题：
- 历史端点 `apphis`（项目现用）：881 成分股并集 5237，只含 30 只 `92` 开头；
- 实时端点 `apphwshhq`：并集 5316，北交所部分是 **43/83/87 旧代码**（63 只）+ 30 只 `92` → 与本地 `core_stock` 的 920xxx 仍对不上，未映射反而 314 只。
所以**把 `KAIPANLA_INDUSTRY_API_URL` 换成实时端点修不好**（当时结论：补齐只能自己维护 43/83/87→920xxx 的映射）。旧族 80xxx 概念走 `apphis` 是**带 920xxx 的**，这才是旧族只缺 5 只的原因。**最终没有自建映射表**，改为用同花顺行业成分股补齐（下一小节），`unmapped_stock_count` 已回到 **0**。

**资金流历史只剩 1 天**：清库后 `read_intraday_history(days=5)` 只有 2026-09-11，`missing_trade_dates` 报 09-07~09-10 四天。端点回补也救不回来（实时端点带 `Date` 的滚动窗口只到 09-09，更早为 0）。`read_intraday` 返回的是 `time_points` + `series`（**没有 `inflows`/`outflows` 键**，别读错），单日单槽时 50 点曲线正常（末值延伸到全天）。

### 北交所行业归属：用同花顺行业成分股增量补齐（2026-09-12 已落地）

**结论：能，且是唯一可行路径**。同花顺（`HITHINK_FINANCE_*`，`X-api-key` 头）的**正向**接口可用：行业清单 1 次 + 逐个行业取成分股 90 次 = **91 个请求**（0.35s 间隔约 35s；按 `.env` 的 `REQUEST_DELAY_SECONDS=1` 约 90s）。

- `GET /api/a-share-index/catalog/ths-index-list?tag=industry` → **320 条**（`881xxx.TI` 90 个 + `884xxx.TI` 230 个），字段仅 `thscode`/`name`，一次全量无分页。
- `GET /api/a-share-index/constituents/ths-stock-list?thscode=881121.TI` → 成分股 `item[].thscode/ticker/name`。
- **只用 881 的 90 个行业就 100% 覆盖全市场**：并集 **5562 只**（含 **343 只 920xxx**），项目 09-11 的 5550 只有效股票**未覆盖 = 0**，那 313 只未映射的**一只不落全部补回**。884 是 881 的**子集**（884 独有 = 0，仅 884 覆盖 4693、缺 869 只），无需拉。

**同花顺 881 与开盘啦 881 是同一套分类**（关键发现）：共同 **90 个代码名称 100% 逐字一致**；开盘啦 104 = 这 90 个 + **14 个旧代码**（881104 农业服务、881106 石油矿业开采、881110 化工合成材料、881111 化工新材料、881113 有色冶炼加工、881119 仪器仪表、**881120 电力设备**、881127 非汽车交运、881147 环保工程、881150 公交、881154 园区开发、881161 酒店及餐饮、**881163 计算机应用**、881176 房地产服务），同花顺没有这 14 个。开盘啦的行业**重叠**正来自这 14 个旧代码（881120 含 881279 的成分），而同花顺的 **90 个行业完全互斥**：成分股计数合计 5562 = 去重并集 5562，重复 0，每只股票**恰好属 1 个行业**。

**同花顺每个行业的成分股都是开盘啦的严格超集**：逐行业比对「仅开盘啦有」**恒为 0**，「仅同花顺有」为正（汽车零部件 +33、通用设备 +28、专用设备 +23、化学制品 +15…），多出来的就是 920xxx 北交所 + 少量新股（如 881121 半导体多 688432 与 6 只 920xxx）。所以补北交所可以只做**增量合并**，不必推翻开盘啦的 104 个行业。

**四个必须知道的限制**：
1. **反查接口不存在**：`/api/a-share/stock-basics`、`/api/a-share/ths-index-membership` 实测 **HTTP 404 Route not found**（文档标"敬请期待"）。没有"输入股票→输出行业"的接口，只能靠正向成分股**全量倒排**。`/api/meta/tickers/search` 可用但**只返回 thscode/ticker/name**，无行业字段。
2. **不能批量传 thscode**：逗号形式分别报 `code=1002` / `code=1001`；`limit`/`offset` 传了无效。必须逐个行业一次请求。
3. **成分股接口无日期参数**：多传 `date`/`trade_date` 返回完全相同的结果 → **只有"当前"成分快照，不可回溯历史交易日**。回补历史日只能拿"今天"的归属去填，语义上是近似（行业归属本身变动很慢，实践可接受）。这正好和开盘啦相反（开盘啦能按 `Date` 取历史，但缺北交所）。
4. **`/api/meta/tickers/list` 的 `exchange` 参数无效**：传 `exchange=BJ` 仍返回全市场 5571 只（前缀 `60`1702/`68`618/`00`1495/`30`1409/`92`347）——不要指望用它筛北交所，但可确认同花顺侧 920xxx 总数 **347**（与本地 `core_stock` 一致；本地 **43/83/87 开头为 0 只**，所以开盘啦给旧代码必然对不上）。

#### 落地实现（最小改动方案：保留开盘啦 104 个行业，只补成员）

**新增/改动的文件**：
- `core/integrations/hithink/contracts.py` —— 新增 `HithinkIndustryIndex(thscode, industry_code, industry_name)`。
- `core/integrations/hithink/mappers.py` —— `map_industry_index()`（只接受 `.TI` 后缀，否则 `HithinkPayloadError`）、`map_industry_constituent()`。
- `core/integrations/hithink/client.py` —— `list_industry_indices()`（`tag=industry`）、`list_industry_constituents(thscode)`（拒绝逗号）。
- `core/services/industry_backfill.py`（新）—— `backfill_missing_industry_stocks(records, *, client=None)`。
- `core/services/sync_industries.py` —— 在开盘啦收完之后、写库之前调用补全；`IndustrySnapshotSyncResult` 加 `backfilled_stock_count`。
- `core/management/commands/sync_kaipanla_industry_snapshot.py` —— 成功消息追加 `Backfilled N stock assignments from Hithink.`
- `backend/tests/test_source_policy.py` —— 把两个新端点登记进 `HITHINK_ENDPOINTS`（**这是刻意的审批守卫，新增同花顺端点必须同步登记，否则 `test_hithink_client_uses_only_approved_...` 失败**）。

**配置**：`.env` / `.env.example` 新增 `HITHINK_INDUSTRY_BACKFILL_ENABLED`（默认 `1`，即缺省开启）。设 `0` 时补全整段跳过、命令不碰同花顺。**补全失败会整体失败**（不静默退回 313 那个状态）；同花顺挂了就把它设 0 再跑。

**语义（这是"最小改动"的关键）**：
- **只增不删**。开盘啦的成员是权威，同花顺只填它没有的；实测"仅开盘啦有"恒为 0，所以并集等价于用同花顺覆盖，但代码上仍是纯增量。
- **只补同花顺也有的那 90 个代码**。884xxx 跳过（是 881 的子集，补进去只会制造重叠）；开盘啦多出的 14 个旧代码（881120 等）没有同花顺对应，跳过 → 实测这 14 个行业里 **0 只北交所成员**。
- 补进来的代码**必须存在于本地 `core_stock`**，否则是永远匹配不上日行情的死数据。
- 每只北交所股票**恰好归属 1 个行业**（同花顺 90 个行业互斥）。

**实测结果（2026-09-12 20:22 真实执行，2026-09-11 业务日）**：开盘啦阶段 104 个行业 / 240.5s → 同花顺阶段 90 个行业 / **5.7s** / **added=325** → `industry_snapshot | 2026-09-11 | complete | 104 | 104 | 0`。快照成员并集 **5562 = 5237（开盘啦）+ 325**，含 **343 只 920xxx**；当日 5550 只有效股票**未映射 = 0**（原 313）。重建 `build_stock_moves`(49) / `build_sector_momentum`(40 行=2 指标×20) / `build_hundred_day`(104 行业汇总 + 331 个股 + 100 趋势)，`sector_momentum.unmapped_stock_count` 由 313 → **0**，四个模块 `read_*` 均 `warnings=()`、`stale=False`。样例：920045 蘅东光 → `881129 通信设备`；881121 半导体 181 → 188（+6 北交所 +688432）。

**测试**：新增 `core/tests/test_industry_backfill.py`（8 例：只补缺的、忽略本地不认识的代码、不删开盘啦成员、跳过同花顺没有的代码、不动 CHILD、开关可关、上游异常向上抛、同一只被两个行业补到时只计一次）。`core/tests/test_hithink_adapter.py` 加 4 例客户端用例。`test_sync_industries_commands.py` 里既有用例在 `setUp` 把补全函数 patch 成空实现（**否则那些用例会去打真实上游**），另加 1 例端到端接线。全量 **294 个用例，只剩 1 个既有环境失败**（`test_runtime_security_settings_are_safe_by_default`，因本地 `.env` 是 `DJANGO_DEBUG=true` + `SESSION_COOKIE_SECURE=false`）；基线 281 个用例同样只有这 1 个，无回归。

## 盘中高频刷新：现状、闸门与可行性（2026-09-12 只读验证）

### 5 分钟板块资金流：代码齐备，但**没有任何调度在跑**

- 链路完整：`SNAPSHOT_INTERVAL_MINUTES=5`、`trading_slots_for_day()` 一天 **50 个槽（09:30…15:00）**、`resolve_snapshot_slot()` 按运行时刻归槽、`fetch_kaipanla_sector_fund_flow` 默认**只允许盘中**（`_is_trading_session()` 要求 `TradingDay` 里有当天）、`read_intraday` 返回 `time_points`+`series`。实测 `query_intraday(2026-09-11)` = 50 点 × 6 曲线。
- **但库内只有 1 个槽**（`2026-09-11 07:00 UTC` = 15:00 北京时间，来自一次 `--latest` 收尾），**盘中槽位一个都没有** → 从未被定时触发过。仓库里没有 cron/launchd/APScheduler/celery，`scripts/` 只有一个 check 脚本，自动化列表为空。推荐 cron 只写在 `docs/manage-commands.md` §9.2（三条 `*/5` 分段 + 一条 15:00）。
- ~~**前端没有任何轮询**~~：2026-09-12 已落地自动刷新，见下方「盘中链路的落地实现」。

### 通用闸门：`latest_eligible_trading_day()` 的 15:00 断点

**盘中把当天数据写进库，页面默认入口仍然显示前一天。** `latest_complete_stock_price_date()` 用 `latest_eligible_trading_day()` 当上限，而后者在"当天 < 15:00"时**主动退一天**。实测 2026-09-11（周五）10:00 与 14:30 都解析到 **09-10**，15:30 才解析到 09-11。三个盘后模块的 `_resolve_read_date()` 都走这条路。

**绕过方式只有显式 `?date=`**：`requested_explicitly = trade_date is not None`（服务层）与 `'date' in request.GET`（视图层）成对判定，显式日期不退回、直接读当天版本并在缺产物时 `_local_generate`。前端 `DatePicker` 可手选当天。**两边语义必须一致**，改一处要同时改。

### 全市场行情快照端点（`/api/a-share/prices/snapshot`）是盘中刷新的唯一可行通道

`get_historical_prices` 是**一只股票一次请求**（5571 只 ≈ 6 分钟串行，实测单只 0.06s，无隐性限速）；`/api/a-share/prices/snapshot` 则是**全市场分页**（省略 `thscodes`，`limit`/`offset`），`limit=1000` 实测 **6 页 / 5571 条 / 1.7s**，字段 `last_price`/`open_price`/`high_price`/`low_price`/`prev_price`/`volume`/`turnover`/`price_change_ratio_pct` 正好够拼 `MarketPrice`。**已于 2026-09-12 接入**：`HithinkClient.list_market_quotes` + `HITHINK_ENDPOINTS` 白名单登记（漏登记会让 `test_hithink_client_uses_only_approved_...` 失败）。

**三个语义差异（用快照写当天日行情前必须处理）**：
1. **`turnover`/`volume` 低位被舍入**（如 979990554.2 → 979990550、181966643 → 181966640）：5571 只里 turnover 2040 只不一致、volume 134 只，相对误差 ~1e-7。日期当天的 `close/open/high/low` 与 `adjust=forward` 历史接口**逐只完全一致**（0 只不一致）。
2. **除权除息日 `prev_price`/`price_change_ratio_pct` 是原始值**，不是除权参考价。实测 601016 在 09-11 除权：历史接口 `adjust=forward` 给 09-10 收盘 3.429（除权后，涨跌幅 −0.554097%），快照给 `prev_price=3.43`、`pct=−0.58309%`。**管线口径是对的，快照那天会错几只**，收盘后历史同步会纠正。
3. **停牌股返回 `last_price=null` + `volume/turnover=0`**（09-11 有 21 只），必须映射成 `has_valid_trade=False` 且不写价；**新股/复牌本地 `pre_close` 为 None 时涨跌幅应为 None**（688801 在 09-11 上市，快照给 +179.22%，管线给 None）。历史接口还支持 `adjust=none`（`raw`/`bfq` 报 `1002`）。

### 交易日历必须当天重同步

`/api/a-share/calendar/trading-days` 是**以今天为锚回溯一年**的滚动窗口（2026-09-12 拉到 2025-09-12→2026-09-11 共 242 天），**不返回未来交易日**。`sync_trading_calendar` 是 `TradingDay.objects.all().delete()` + 重建，**必须每天开跑前执行**（耗时 0.14s）：`fetch_kaipanla_sector_fund_flow` 的盘中判定和 `sync_stock_daily_prices` 的 `--date` 校验都要求当天在日历里（后者直接 `ValueError`）。周六/周日拉不到当天是正常的。**"盘中时上游是否包含当天"尚未实测过（周末无法验证）**，周一开盘先确认一次。

### 盘中半小时刷新的实测成本（干跑通过，未写库）

把实时快照拼成 `CompleteMarketSnapshot` 后三个分析全部跑通：`get_complete_market_snapshot` 0.55s、`build_stock_move_analysis` ~0s、`build_sector_momentum_analysis` 0.02s、`load_hundred_day_source_data` **4.4s**、`build_hundred_day_analysis` 0.32s → **全链路约 2s 抓取 + 6s 本地重建**，半小时一次绰绰有余。

另两个副作用要预期：
- **`sync_stock_daily_prices --date` 单日路径不做变更比对**，每次运行都 upsert 全部 5571 行并 `begin_publication` 发布新版本（只有 `init_stock_daily_prices` 会 diff、无变化时**不**发版本）。盘中每 30 分钟一次 = 当天 12 个版本，三个模块每次都会因 `source_daily_price_version` 变化而重算，产物表按版本累积旧行。
- 首次查看某版本时读路径会**持锁现算**；并发第二个请求拿到的是 `DatasetLocked` → `CompleteMarketDataUnavailable`，**显式带日期时视图返回 404 `DATA_NOT_AVAILABLE` 而不是 202**，用户看到"空"。

### 盘中链路的落地实现（2026-09-12 已完成，含两个坑）

- **命令**：`refresh_intraday_quotes [--date] [--dry-run]` → `sync_daily_prices.refresh_intraday_daily_prices()`。分页抓全市场快照（50 页防呆），只保留本地活跃股票；**快照里没有的股票跳过而不是清零**（"没收到"≠"停牌"，补缺仍归盘后历史同步）。复用 `_begin_runs`/`_upsert`/`_split_changed_records`/`_complete_covering_runs`，与 `sync_stock_daily_prices` 同语义；**无变化不发新版本**。
- **口径**：`pre_close`/`change_percent` 一律用库内上一交易日收盘重算（`_previous_closes` 按整天查，不用 `stock_id__in` —— 5571 个绑定参数会撞 SQLite 上限）；停牌落 `has_valid_trade=False` 且价格/成交量全 `None`；本地无前收则涨跌幅 `None`。闸门 `INTRADAY_QUOTE_MIN_COVERAGE_RATIO`（0.95）与 `INTRADAY_QUOTE_PAGE_SIZE`（1000）在 `.env`，覆盖率不足整体失败、不标 complete。
- **日期闸门**：`latest_complete_stock_price_date()` 放宽上限 —— `eligible_day < today` 且**当天已有 complete 版本**时提到 today，否则不变。**不动 `latest_eligible_trading_day()`**（"是否已收盘"的语义归盘后管线）。
- **调度**：`scripts/intraday_orchestrator.sh {calendar|fundflow|quotes}`（自行判断 09:30-11:30 / 13:00-15:00，时段外 `exit 0`；`quotes` 只在行情刷新成功后按 `ENABLED_MODULES` 重建三模块）+ `install_intraday_launchd.sh` / `install_intraday_cron.sh`。日志在 `backend/data/intraday-logs/`。
- **坑 1（本机无法自动安装调度）**：`/usr/bin/crontab` 写入报 `Operation not permitted`（macOS TCC 需完全磁盘访问）；`launchctl bootstrap gui/501` 即使绕沙箱、即使换最小 plist 也报 `Bootstrap failed: 5: Input/output error`（只接受来自自己登录会话的 bootstrap）。**必须让用户在 Terminal.app 里跑安装脚本**，再用 `status` / `crontab -l` 确认。
- **坑 2（前端 hook）**：`usePolledResource` 里 `apiClient` 必须经 ref 持有、**不能进 effect 依赖数组** —— 调用方每次渲染新建 client 对象会让 effect 无限重跑，测试这样写直接把 node 跑到 OOM（`Reached heap limit`）。测试也要在同一作用域建一次 client 实例。
- **前端**：新增 `usePolledResource.js` + `marketSession.js`；四个 hook 薄封装（资金流 5 分钟、其余三页 30 分钟，**手选历史日期时 `pollIntervalMs=0`**）。各页状态区显示"更新于 HH:MM"。`useKaipanlaData` 传 `dataNotAvailableCode: null` 保持"404 即错误态"。
- **已知代价**：盘中每 30 分钟一个版本，三个模块按版本累积结果行（一天约 11 轮），暂不清理；快照 `volume`/`turnover` 舍入（~1e-7）靠盘后历史同步纠正。

## 数据库迁移：必须逐库执行（2026-09-12 踩坑，代价很大）

**标准姿势是逐库跑**（`docs/deployment.md` 与 `docs/manage-commands.md` 都这么写）：

```bash
python manage.py migrate --database=default
python manage.py migrate --database=kaipanla
python manage.py migrate --database=stock_moves
python manage.py migrate --database=sector_momentum
python manage.py migrate --database=hundred_day
```

**裸 `migrate`（不带 `--database`）只作用于 `default`，而且它会撒谎**：`db_router.allow_migrate` 让业务 app 的 operation 在 `default` 上变成 no-op，可 Django **照样打印 `Applying stock_moves.0005_... OK`**，并把记录写进 `default` 库的 `django_migrations`。结果是"迁移全绿"但业务库里一个字段都没动 —— 排查时要直接 `PRAGMA table_info(<业务库表>)` 看列名，别看迁移命令的输出。

**第二个坑：Django 在 SQLite 上把 `RenameField` 编译成 `-- (no-op)`**（`sqlmigrate` 实测输出确认）。字段改名**必须**这样写，否则列名不动：

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

SQLite 3.25+ 的 `RENAME COLUMN` 原地改名、**数据完整保留**（实测 49 行与 662 行逐条无损失）。反之，若让 `makemigrations` 自动检测，非交互模式下会把改名判成 remove + add —— **直接删掉整列数据**。

**`sqlmigrate` 也不能用来判断业务库会发生什么**：它默认连 `default`，对业务 app 的 operation 一律显示 `(no-op)`（同样因为 router）。要验证只能真跑 + `PRAGMA` 复查。

## 应用日志体系（2026-09-12 落地，改日志前先读这一节）

- **两路日志，都由环境变量控制、改完重启即生效**：`DATA_COMMAND_LOG_LEVEL`（管理命令 + 进度行）、`DJANGO_LOG_LEVEL`（`core` + 四业务模块 + Web 访问日志）、`DJANGO_LOG_FORMAT`（`plain`=单行 `key=value` / `json`）、`DJANGO_REQUEST_LOG_SLOW_MS`（默认 1000）。用户文档在 `docs/manage-commands.md` §3.7 与 `docs/deployment.md` §2.1。
- **`settings.LOGGING` 的关键前提**：`django.utils.log.configure_logging` 是**先 `dictConfig(DEFAULT_LOGGING)` 再应用 `settings.LOGGING`**，所以**重定义 `console` handler 就能让 `django.request` / `django.server` 一并走自定义格式**；`disable_existing_loggers` 必须 `False`，否则这两个 logger 被静音。改 `LOGGING` 前先复读 `django/utils/log.py`，别凭记忆。
- **`core/logging.py` 的三个入口**：`log_command_event`（命令生命周期）、`log_command_progress`（进度行）、`log_event(logger, event, *, level, exc_info, **fields)`（业务事件）。`log_event` 渲染单行 `key=value`，并把 `event`/`event_fields` 放进 `extra` 供 `JsonFormatter` 提升为顶层键。
- **`LogRecord` 保留属性**：`extra` 覆盖 `module`/`name`/`message` 等既有属性会抛 `KeyError: "Attempt to overwrite 'module' in LogRecord"`。`_RESERVED_RECORD_KEYS` 先过滤，这类字段留在 message 里、不进 `event_fields`。
- **`RequestContextFilter` 是安全网**：它给**每条**记录（含 Django 自身与第三方）兜底注入 `request_id`，格式串里的 `%(request_id)s` 才能对任意记录安全求值。请求上下文用 `request_logging_context`（`ContextVar`）承载，不逐层透传。
- **请求关联**：`RequestLoggingMiddleware`（`core/middleware.py`）从入站 `X-Request-ID` 取 id，经 **`^[A-Za-z0-9._-]{1,64}$` 白名单校验**（防日志伪造），并回写响应头。**事件分级口径**：quiet 路径（`/static/`、`/favicon.ico`、`/api/core/health/`）→ DEBUG；≥ `REQUEST_LOG_SLOW_MS` → WARNING `http_request_slow`；异常逃出中间件 → ERROR `http_request_failed` 后 `raise`；其余 → INFO `http_request`。**4xx 不升级**（严重级别由 `django.request` 负责，避免重复计数）。
- **读路径事件（排查"页面为什么慢/为什么是旧数据"主要看这几个）**：`read_generated`（本次请求现算）+ `read_served`（DEBUG）/ `read_stale_fallback`（WARNING，退回旧数据，页面同时显示"正在展示旧数据"）/ `read_unavailable`（WARNING 后 raise，API 多返回 404/202）。三个盘后模块的 `read_path.py` 统一是「`read_*` 薄包装 + `_read_*` 原逻辑」结构，**加日志只动包装层，不要往业务逻辑里塞**。
- **上游日志口径**：重试记 WARNING（`upstream_retry` / `page_retry`）、放弃记 ERROR（`upstream_failed` / `page_failed`）、**成功只记 DEBUG** —— 一次同步几千次调用，INFO 会把日志淹掉。`kaipanla/services/fetcher.py` 原来失败页静默 `return None`，是最典型的"无痕"点，已补。
- **`kaipanla/services/read_path.py` 的远程修复**：`_repair_current_snapshot` 原有多个静默 `return False`，现已全部补日志（`repair_skipped`/`repair_discarded`/`repair_failed`/`repair_published`），丢弃原因由纯函数 `_repair_discard_reason()` 给出。计时**统一用 `perf_counter`**（`elapsed_ms` 要求单调时钟，不要混 `monotonic`）。
- **脱敏与防注入是硬要求**：所有字段先过 `redact_sensitive_text()`，再折叠换行（防日志注入）、单字段截断 500 字符。**登录失败只记 username、绝不记密码**。`extra` 里的 `JsonFormatter` 时间用 `timezone.localtime` 输出本地 ISO。新增日志一律走 `log_event`，不要裸 `logger.info(f'...')`。
- 单测在 `backend/core/tests/test_request_logging.py`（17 例，覆盖访问行/`X-Request-ID`/慢请求/4xx 不升级/降噪/异常重抛/`log_event` 脱敏与保留字段/`JsonFormatter`/登录三事件/上下文清理）。

## 命令契约、日志与性能

- `BaseDataCommand`（`core/management/base.py`）用 `dataset_lock` + `log_command_event` 输出生命周期事件 `data_command_started`/`finished`/`failed`/`locked`；子类实现 `run_data_sync`/`format_success_message`/`get_business_date`。
- **命令进度日志**：长耗时命令在 started/finished 之间持续输出事件名 **`data_command_progress`**（字段 `stage` + `processed`/`total`/`percent`/`eta_seconds`，默认**每 30 秒最多一行**，阶段首尾各强制一行）。实现是 `core.logging` 的 `command_logging_context`（`ContextVar` 绑批次身份）+ `ProgressReporter`；`BaseDataCommand.handle` 负责绑定，**服务层可直接调 `log_command_progress(stage, **details)`，不必透传 module_id/batch_id**；无绑定上下文时返回 `False` 且不输出。判断"命令是否卡住"看 `processed` 是否增长。
- **`backend/env.py` 已做配置缓存**（`_PARSE_CACHE`，每 `ENV_CACHE_TTL_SECONDS=5.0` 秒比对一次文件指纹；`get_setting` 先查 `os.environ`，命中就完全不碰文件）。**改这个文件前先读一遍**：曾经的写法 `os.environ.get(name, _file_values().get(name, default))` 让每次取配置都重读整个 `.env`（一次 `init_stock_daily_prices` = 186 次读取，占掉 99% 运行时长，单次 7.9s→0.08s）。新增配置读取复用 `get_setting` 系列，不要自己 `Path('.env').read_text()`。脱敏见 `core/logging.py` 的 `redact_sensitive_text()`。
- 命令类测试要**冻结时间**（`patch('django.utils.timezone.now', return_value=...)`）并建好 `TradingDay` 行，否则槽位判定会跟真实运行日期漂移；`--dry-run` 也会先算槽位，同样需要日历。
- **性能基线**：`get_complete_market_snapshot` ≈0.55s；百日最重 —— `load_hundred_day_source_data` ≈2.8–4.4s（110 万行必须用 `values_list` 批量取值，`select_related` 逐对象要 14.7s）+ `build_hundred_day_analysis` ≈0.32–0.4s，单日按需生成合计 ≈3.5–5s。**`hundred_day/services/flags.py` 的 `compute_high_low_flags` 用双单调队列做滑窗极值（7.7s→0.32s）**，语义由 `tests/test_flags.py` 的"朴素窗口差分测试"锁住（改它必须让该差分测试通过）。`build_stock_move_analysis` ≈0s、`build_sector_momentum_analysis` ≈0.02s。

## 测试与回归清理

- **判回归前先清两样**：`backend/data/locks/*.lock`（`dataset_lock` 残留会让 `call_command` 用例集体报 `DatasetLocked`/`FileExistsError`；锁名 = `sha256('module:dataset')`，可反查归属）与 `backend/cache/`（陈旧条目会让期望 `source='database'` 的用例拿到 `'cache'`）。只认"清完之后的第一次全量运行"。要区分回归与既有失败，用 `git worktree` 建基线树对比（注意 `.env` 在**仓库根**）。
- **跑全量后端测试要加 `CODEBUDDY_SAFE_DELETE_ENABLED=0`**：CLI 的 `sitecustomize.py` safe-delete shim 会拦截 `Path.unlink`（`dataset_lock` 退出时删锁即触发），单个 turn 删除数超过阈值就 `SystemExit(1)`，表现为几十个**无关**用例集体 ERROR。带这个环境变量 + 关闭沙箱才能拿到真实结果。跑完用 `ls backend/data/locks | wc -l` 确认 0 泄漏。
- **当前基线（2026-09-13 05:01，P2 修复后）**：**395 tests / `OK (skipped=1)` / 0 失败 / 0 泄漏锁**；`makemigrations --check --dry-run` → `No changes detected`。前端同批：19 个文件 / 150 条用例全过、`eslint src` 无输出、`vite build` 成功。**上一轮记录的"1 个既有失败"已消除**：`backend/backend/tests/test_security_settings.py::test_runtime_security_settings_are_safe_by_default` 现在会在本机 `.env` 是调试口径（`DJANGO_DEBUG=true`）时 `skipTest` 并写明原因（它就是那个 `skipped=1`），只在生产口径 `.env` 下才真正执行那组断言。**因此不要再按"既有失败"从失败集合里扣这一条** —— 现在的全量是真绿，失败集合为空即为无回归。（用例总数会随迭代增长，别把 395 当固定值。）
- **必须在 `backend/` 目录下跑 `manage.py test`**：从仓库根跑会 `Found 0 test(s)` + `NO TESTS RAN`，且**退出码仍是 0**（2026-09-12 踩到，差点当成"全过"）。因为测试发现以 `cwd` 为起点，仓库根的 `tests/` 里没有 Django 用例。
- 同时跑真实命令与测试会**假连锁**：锁是文件系统级的（`backend/data/locks/*.lock`），不随测试库隔离。特征 = 失败只落在几个不相干的 `call_command` 用例、单独跑那些模块完全正常、套件总耗时明显变长。对策 = 等真实命令结束再跑。
