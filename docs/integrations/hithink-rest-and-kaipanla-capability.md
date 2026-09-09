# 同花顺 REST 与开盘啦行业链路能力验证

**验证日期：** 2026-09-08（Asia/Shanghai）\
**任务：** T01\
**结论：** **通过，可进入实现。** 个股公共市场数据使用同花顺 REST API；行业—股票关系使用开盘啦父行业 → 子行业 → 股票列表链路。Python SDK 不再是本项目依赖或数据源。

## 已批准的数据源边界

### 同花顺 REST：个股公共市场数据

- 鉴权：`X-api-key`，值仅从根目录 `.env` 的 `HITHINK_FINANCE_API_KEY` 读取。
- 股票列表：`GET /api/meta/tickers/list`，使用 `asset_type=a-share` 分页取得全量 A 股。
- 交易日历：`GET /api/a-share/calendar/trading-days`。
- 日线：对每个股票调用 `GET /api/a-share/prices/historical`，固定 `interval=1d` 与 `adjust=forward`，只请求最近一年。

实际最小调用均成功：股票列表、交易日历、单股票最近一年历史日线均返回业务 `code=0`。最近一年日线实测为 242 行，字段包含 `date_ms`、OHLC、`volume` 和 `turnover`。

### 开盘啦：行业—股票关系

行业—股票快照使用历史端点 `https://apphis.longhuvip.com/w1/api/index.php`；板块资金流仍使用实时端点 `https://apphwshhq.longhuvip.com/w1/api/index.php`。两条链路通过独立的 `.env` 配置项 `KAIPANLA_INDUSTRY_API_URL` 与 `KAIPANLA_API_URL` 管理，不能互相替代。

`~/test.py` 已实际验证：

1. `RealRankingInfo` 获取父行业；
2. `SonPlate_Info` 按父行业获取子行业；
3. `ZhiShuStockList_W8` 按子行业分页获取股票列表。

使用业务日期 **2026-09-07** 的样本：父行业“通信”（`801660`）成功获取“光模块”（`801206`，125 只股票）和“PCB”（`801216`，203 只股票）。股票 `000801` 同时出现于这两个子行业，故多行业归属是实际数据语义。

行业—股票快照固定保存四个业务字段：`industry_code`、`industry_name`、`industry_level`（`parent` 或 `child`）和 `stock_codes`（JSON 股票代码数组）。若上游存在无成分股的子行业，保留该 `child` 记录并保存空数组；它不会增加父行业聚合股票。该表不保存历史有效期，也不新增父行业外键；父子关系只在采集阶段使用。


### 开盘啦凭据可选性复核（2026-09-09）

使用本项目根目录 `.env` 的非空 `KPL_DEVICE_ID`、`KPL_USER_ID`、`KPL_TOKEN`，以及完全省略三个表单字段的两组真实只读请求分别复核。两组都成功取得：

1. `RealRankingInfo` 板块资金流完整分页（分别得到 270 条和 266 条；两次请求间的盘中上游快照发生变化）；
2. `RealRankingInfo` 父行业列表（各 270 条）；
3. `SonPlate_Info` 子行业列表（各 15 条）；
4. `ZhiShuStockList_W8` 股票列表（业务日期 **2026-09-08** 的已发布快照，各至少取得有效股票代码）。

结论：三个 `KPL_*` 值都是可选配置；代码仅在值非空时发送相应字段。**这只是当前上游行为的实测结果，不构成稳定的匿名访问承诺。** 同日盘中对业务日期 **2026-09-09** 的股票列表请求在两种凭据模式下都返回业务码 `1020`，说明该失败与是否携带凭据无关；行业—股票同步应使用已发布的交易日快照，不能把盘中当日未发布数据误判为认证失败。

## 实施约束与风险

- 同花顺 REST 与开盘啦调用均采用可配置低并发、请求间隔、有限退避和超时。
- HTTP 429 或业务码 `4001`、认证/权限错误、空数据和上游超时必须保留最近成功版本，不覆盖为完整版本。
- 测试模拟上游响应，不依赖真实凭据；不得输出、记录或提交 API Key、Token 或 Device ID。
- 禁止个股爬虫、浏览器自动化、上交所/深交所旧下载和 Baostock。
- 公开文档未公布固定 QPS、并发或每日额度；此前连续请求曾遇到 HTTP 429。因此，逐股票最近一年初始化必须低频顺序执行，并可从失败处恢复。
