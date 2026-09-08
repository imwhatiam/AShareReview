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

`~/test.py` 已实际验证：

1. `RealRankingInfo` 获取父行业；
2. `SonPlate_Info` 按父行业获取子行业；
3. `ZhiShuStockList_W8` 按子行业分页获取股票列表。

使用业务日期 **2026-09-07** 的样本：父行业“通信”（`801660`）成功获取“光模块”（`801206`，125 只股票）和“PCB”（`801216`，203 只股票）。股票 `000801` 同时出现于这两个子行业，故多行业归属是实际数据语义。

行业—股票快照固定保存四个业务字段：`industry_code`、`industry_name`、`industry_level`（`parent` 或 `child`）和 `stock_codes`（JSON 股票代码数组）。该表不保存历史有效期，也不新增父行业外键；父子关系只在采集阶段使用。

## 实施约束与风险

- 同花顺 REST 与开盘啦调用均采用可配置低并发、请求间隔、有限退避和超时。
- HTTP 429 或业务码 `4001`、认证/权限错误、空数据和上游超时必须保留最近成功版本，不覆盖为完整版本。
- 测试模拟上游响应，不依赖真实凭据；不得输出、记录或提交 API Key、Token 或 Device ID。
- 禁止个股爬虫、浏览器自动化、上交所/深交所旧下载和 Baostock。
- 公开文档未公布固定 QPS、并发或每日额度；此前连续请求曾遇到 HTTP 429。因此，逐股票最近一年初始化必须低频顺序执行，并可从失败处恢复。
