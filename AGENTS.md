# 仓库指南

## 项目结构与模块组织

这是一个精简的 Django 后端。`backend/manage.py` 是命令入口；`backend/backend/` 包含设置、URL 和部署入口。在 `backend/` 内创建应用，并将模型、视图、服务、迁移和测试放在一起。不要提交数据库、虚拟环境、缓存或 `.env`。

## 开发命令

在 `backend/` 目录下运行：

- `python manage.py runserver` —— 启动开发服务器。
- `python manage.py migrate` / `makemigrations` —— 应用或生成迁移。
- `python manage.py test` —— 运行测试。
- `python manage.py check` —— 校验配置。

使用虚拟环境；提交依赖。

## 编码与测试规范

遵循 PEP 8 和四空格缩进。模块与函数使用 `snake_case`，类使用 `PascalCase`，应用名使用小写。将业务逻辑放在 services 中。使用 Django 的 `TestCase`；测试文件命名为 `test_*.py`，方法命名为 `test_<行为>`。覆盖回归场景。

如果需要访问网页或者发送web api请求进行测试，需要提前询问是否已有本地开发环境部署好的前后端服务及服务地址，如果没有，不要自行搭建测试环境。

## 有意设计，不要"顺手统一"

下列各处的"不统一"都是有意设计。动手前先看理由，不要为"统一""简洁"改掉它们：

| 位置 | 为什么不动 |
| --- | --- |
| 三个盘后模块各自的 `models.py` / `analysis.py` | 领域规则确实不同（`stock_moves` 的六个分组、`sector_momentum` 的两口径评分、`hundred_day` 的 99 日窗口）。为统一而合并会破坏 `test_module_isolation.py` 守护的隔离边界 |
| 三个 `services/industry_source.py` 垫片 | 让每个模块**显式声明自己的输入契约**，是有意设计；`core/services/industry_snapshot.py` 的文档串按名字指着它们 |
| 三份上游重试循环（`core/integrations/hithink/client.py`、`core/integrations/kaipanla/client.py`、`kaipanla/services/client.py`） | 三种日志契约不同（字段、级别、sleep 时机），合并会压成一个，丢掉真实的失败模式覆盖 |
| `core/services/locking.py` 的陈旧锁回收 | 有真实失败模式（SIGKILL 后 `finally` 不执行）与明确取舍（宁可漏判不误判，避免双写） |
| `core/services/file_cache.py` 用 `DjangoJSONEncoder` 而非 `default=str` | 缓存命中与未命中在线路上必须完全一致，且要拒绝不可表示对象 |
| `hundred_day/services/flags.py` 的单调双端队列 | 把 99 日滚动极值从 O(n·99) 降到 O(n)，属"复杂度换正确性能" |
| `frontend/src/shared/ui/DatePicker.jsx`（339 行单文件） | 全仓只有这一个弹层，抽 `usePopoverPlacement` / `useFocusTrap` 属于"为 1 个调用方建抽象" |
| 四个图表的内联高度（`HistoryChart` 380 / `IntradayChart` 380 / `RatioTrendChart` 340 / `MomentumChart` 360） | 340 / 360 是各自独立的设计取值、没有共同语义；只有 380/380 那一对必须相等（同一容器切换） |
| `kaipanla` 表 8 个只写不读的列（`change_pct` / `main_buy` / `main_sell` / `large_order_net_inflow` / `volume_ratio` / `turnover_amount` / `float_market_cap` / `total_market_cap`） | 采集型系统先把上游给的观测值落库备查是合理形态；它们不是别的行的函数，删了要重采才有。`kaipanla/models.py` 顶部有说明 |

判据（什么才算"值得抽 / 值得删"）与量化方法见技能 `.workbuddy/skills/code-complexity-audit/SKILL.md`。

## 配置

所有开发与测试配置值都必须从根目录的 `.env` 读取并写入，包括凭据、URL、开关和超时时间。切勿在代码、测试、fixtures 或命令中硬编码配置。保持 `.env` 不被跟踪，并在 `.env.example` 中记录安全占位符。生产环境必须禁用 `DEBUG`、配置 `ALLOWED_HOSTS`，并从 `.env` 加载 Django 密钥。

## 数据源

所有个股和板块数据，都需要先通过 python manage.py 命令从数据源获取，然后存入本地数据库，再通过 web api 从本地数据库获取。通过 web api 获取数据时，优先使用本地文件系统缓存，然后使用本地数据库，最后使用数据源。

### 个股数据源

个股公共市场数据走同花顺 REST API，客户端是 `backend/core/integrations/hithink/client.py`（`requests` + 请求头 `X-api-key`，密钥来自 `.env` 的 `HITHINK_FINANCE_API_KEY`，地址来自 `HITHINK_FINANCE_BASE_URL`）。当前使用的端点：

- `/api/meta/tickers/list` —— 全量 A 股清单（`asset_type=a-share`，分页）。
- `/api/a-share/prices/historical` —— 个股日线（固定 `interval=1d`、`adjust=forward`）。
- `/api/a-share/prices/snapshot` —— 全市场实时快照，仅用于盘中刷新当天行情。
- `/api/a-share-index/catalog/ths-index-list`、`/api/a-share-index/constituents/ths-stock-list` —— **只用于补齐北交所行业归属**（见下）。

**必须使用 REST 接口，不要使用爬虫、浏览器自动化或页面抓取。** 上游能力与实施约束见 `docs/data-sources/web-api.md` §6。

**交易日不走上游**：交易日历的唯一来源是第三方库 `chinese-calendar`，实现在 `core/services/calendar.py`（`is_trading_day` / `previous_trading_day` / `recent_trading_days` / `trading_days_between` / `latest_trading_date` / `latest_eligible_trading_day`）。**不要新增任何"从上游同步交易日历"的端点、命令或本地日历表**；需要交易日一律调这几个函数。`chinese-calendar` 按年内置假期表，未覆盖的年份退化为"工作日即交易日"并每年报一次 WARNING。

行业—股票的正式来源是开盘啦行业快照；同花顺指数接口**只做增量补齐**：开盘啦 881 行业族给北交所股票用的是旧代码（43/83/87），313 只 `920xxx` 无法归入任何行业，由 `core/services/industry_backfill.py` 用同花顺 881 行业成分股**只增不删**地补上（开关 `HITHINK_INDUSTRY_BACKFILL_ENABLED`，默认开）。这只处理北交所的归属问题，不改变「行业关系以开盘啦为准」的口径。

### 板块资金流数据源

这些请求仅被批准用于板块资金流数据，而非个股数据。这些请求相关的 url 和参数，也必须是可配置的，并从 `.env` 加载。

开盘啦有两条不能互相替代的端点：行业—股票快照走历史端点 `KAIPANLA_INDUSTRY_API_URL`（`https://apphis.longhuvip.com/w1/api/index.php`），板块资金流走实时端点 `KAIPANLA_API_URL`（`https://apphwshhq.longhuvip.com/w1/api/index.php`）。

#### 开盘啦

**POST URL:** `https://apphwshhq.longhuvip.com/w1/api/index.php`（来自 `.env` 的 `KAIPANLA_API_URL`）

以 `application/x-www-form-urlencoded` 请求体发送参数示例（**实际取值一律来自 `.env`，不要照抄这里的字面量**）：

- `Order=1`（`KAIPANLA_FLOW_ORDER`）、`a=RealRankingInfo`（`KAIPANLA_FLOW_ACTION`）、`c=ZhiShuRanking`（`KAIPANLA_FLOW_CONTROLLER`）、`st=80`（`KAIPANLA_FLOW_PAGE_SIZE`）
- `PhoneOSNew=1`、`VerSion=5.23.0.4`、`apiv=w44`
- `Type=1`（`KAIPANLA_FLOW_TYPE`）、`ZSType=4`（`KAIPANLA_FLOW_ZS_TYPE`）
- `Index`：页偏移量（`0`、`80`、`160`，...）
- `DeviceID`：来自 `.env` 的 `KPL_DEVICE_ID` 的值
- 当 `.env` 中对应的值非空时，添加来自 `KPL_USER_ID` 的 `UserID` 和来自 `KPL_TOKEN` 的 `Token`。

**`ZSType` 必须是 `4`（881xxx 行业族），且与行业链路的 `KAIPANLA_INDUSTRY_PARENT_ZS_TYPE` 同族，配套的 `Type` 固定为 `1`。** 两处不一致会混族；改用其他族时必须回滚并重算全部行业相关产物与缓存（见 `.workbuddy/memory/MEMORY.md` 第 1 节）。

## 提交与拉取请求

使用祈使语气的提交信息。拉取请求必须总结变更、列出验证方式、关联 issue，并明确指出迁移、配置或上游契约的变更。对于可见的变更，请附上截图。
