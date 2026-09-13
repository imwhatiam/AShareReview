# `python manage.py` 命令使用手册

> **适用版本：2026 年 9 月 12 日的当前代码库。** 这是一份面向本地开发机和阿里云部署机的运维手册，说明本项目当前实际注册的 Django 管理命令、依赖关系、执行顺序和故障处理方法。
>
> 所有示例均假设当前工作目录为仓库根目录：`<repo>`。除非另有说明，命令都必须在 `backend/` 目录中执行。

## 目录

- [1. 当前命令与模块范围](#1-当前命令与模块范围)
- [2. 运行前准备](#2-运行前准备)
- [3. 通用约定](#3-通用约定)
- [4. 首次部署与数据初始化](#4-首次部署与数据初始化)
- [5. 公共基础数据命令（`core`）](#5-公共基础数据命令core)
- [6. 开盘啦板块资金流命令（`kaipanla`）](#6-开盘啦板块资金流命令kaipanla)
- [7. 盘后派生分析命令](#7-盘后派生分析命令)
- [8. Django 运维与诊断命令](#8-django-运维与诊断命令)
- [9. 推荐的 crontab 执行策略](#9-推荐的-crontab-执行策略)
- [10. 常见错误、恢复与排查](#10-常见错误恢复与排查)
- [11. 数据库、缓存与运行状态](#11-数据库缓存与运行状态)
- [12. 命令速查表](#12-命令速查表)

---

## 1. 当前命令与模块范围

当前仓库已注册以下四个业务模块，以及一个不可删除的公共基础库 `core`：

| 模块 | Django App | 数据库 | 与命令有关的职责 |
| --- | --- | --- | --- |
| 公共基础库 | `core` | `backend/data/core.sqlite3` | 股票主数据、交易日历、开盘啦行业—股票关系、公共日行情、数据版本和运行状态。 |
| 开盘啦板块资金流 | `kaipanla` | `backend/data/kaipanla.sqlite3` | 获取并发布完整的开盘啦板块资金流快照。 |
| 大涨跌幅与大成交量个股 | `stock_moves` | `backend/data/stock_moves.sqlite3` | 从本地公共日行情构建上证/深证/北交所各自的涨跌两组，共六组。 |
| 板块动量 | `sector_momentum` | `backend/data/sector_momentum.sqlite3` | 从本地公共日行情和板块关系构建板块动量排名。 |
| 百日新高新低占比 | `hundred_day` | `backend/data/hundred_day.sqlite3` | 从本地公共日行情和板块关系构建百日新高、新低结果。 |

### 当前未注册的命令

当前代码库**没有** `fetch_eastmoney_sector_fund_flow` 或其他东方财富管理命令，也没有独立的 `eastmoney` Django App。因此本手册不会提供不存在的东方财富命令示例。待该模块实际实现并注册命令后，应同步补充本手册。

### 数据源实现提示

当前实现中的股票主数据、交易日历和前复权日行情命令读取 `HITHINK_FINANCE_*` 配置，并且命令帮助明确标注为 Hithink REST 数据源；开盘啦资金流和行业关系读取 `KAIPANLA_*` / `KPL_*` 配置。请以仓库当前实现和根目录 `.env.example` 为配置依据；不要在命令行、crontab 或日志中写入 API Key、Token 等真实凭据。

---

## 2. 运行前准备

### 2.1 进入后端目录并激活虚拟环境

```bash
cd <repo>/backend
source /path/to/venv/bin/activate
```

若项目已经使用当前 shell 的 Python 虚拟环境，只需执行：

```bash
cd <repo>/backend
python --version
python manage.py check
```

### 2.2 根目录 `.env`

所有运行时配置均从仓库根目录 `.env` 加载。首次部署时：

```bash
cd <repo>
cp .env.example .env
chmod 600 .env
```

至少确认以下类别已经按环境填写：

| 类别 | 关键变量 | 用途 |
| --- | --- | --- |
| Django | `DJANGO_SECRET_KEY`、`DJANGO_DEBUG`、`DJANGO_ALLOWED_HOSTS`、`DJANGO_TIME_ZONE` | Django 安全和时区。生产必须 `DJANGO_DEBUG=false`。 |
| SQLite | `CORE_DATABASE_PATH`、`KAIPANLA_DATABASE_PATH`、`STOCK_MOVES_DATABASE_PATH`、`SECTOR_MOMENTUM_DATABASE_PATH`、`HUNDRED_DAY_DATABASE_PATH` | 五个数据库文件的位置。 |
| 缓存/锁 | `FILE_CACHE_DIRECTORY`、`LOCK_DIRECTORY`、`FILE_CACHE_*`、`REMOTE_REPAIR_ENABLED`、`REMOTE_REPAIR_HARD_TIMEOUT_SECONDS`、`REMOTE_REPAIR_RETRY_AFTER_SECONDS` | API 文件缓存、避免同一数据集并发同步，以及**仅供板块资金流**使用的请求侧远程兜底开关（`REMOTE_REPAIR_ENABLED`）与它的耗时上限（`REMOTE_REPAIR_HARD_TIMEOUT_SECONDS`）；`REMOTE_REPAIR_RETRY_AFTER_SECONDS` 只是响应里的重试提示值，不改变抓取时长。三个盘后模块的按需生成是不访问上游的本地计算，不读这些配置。 |
| 股票公共数据 | `HITHINK_FINANCE_BASE_URL`、`HITHINK_FINANCE_API_KEY`、超时、限速、重试变量 | 股票表、交易日历、日行情同步。 |
| 开盘啦 | `KAIPANLA_API_URL`、`KAIPANLA_INDUSTRY_API_URL`、`KPL_*` 和请求行为变量 | 资金流和行业关系同步。 |

`KPL_DEVICE_ID`、`KPL_USER_ID`、`KPL_TOKEN` 可以为空。为空时，对应字段不会发送到开盘啦；非空时才附加。不要将真实 `.env` 提交到 Git。

### 2.3 运行时目录与权限

部署账户必须可写以下目录：

```bash
cd <repo>
mkdir -p backend/data backend/data/locks backend/cache backend/logs
```

- `backend/data/`：SQLite 数据库文件。
- `backend/data/locks/`：数据集同步锁。
- `backend/cache/`：Web API 文件缓存。
- `backend/logs/`：推荐用于 crontab 标准输出和错误输出的日志目录。

这些均为运行时数据，**不应提交**到 Git，也不应在不确认后果时删除。

---

## 3. 通用约定

### 3.1 命令格式

```bash
cd <repo>/backend
python manage.py <command> [options]
```

查看命令帮助：

```bash
python manage.py help <command>
# 例如：
python manage.py help sync_stock_daily_prices
```

查看 Django 发现的全部命令：

```bash
python manage.py help
```

### 3.2 `--dry-run`

所有自定义数据命令支持：

```bash
--dry-run
```

它用于验证上游连接、请求解析、完整性校验和待写入数据规模；成功时不会发布正式数据。

**注意：** `--dry-run` 并不表示“完全离线”。它仍可能访问远程数据源，因而仍可能遇到网络错误、凭据错误、限流、上游拦截或耗时较长的问题。

推荐先执行一次 dry run：

```bash
python manage.py sync_stock_master --dry-run
python manage.py sync_kaipanla_industry_snapshot --dry-run
python manage.py fetch_kaipanla_sector_fund_flow --dry-run
```

### 3.3 `--date DATE`

三个派生分析命令和日行情增量命令要求 ISO 日期：

```bash
--date YYYY-MM-DD
```

例如：

```bash
python manage.py sync_stock_daily_prices --date 2026-09-08
python manage.py build_stock_moves --date 2026-09-08
```

`--date` 应为 A 股交易日，且应与已经成功发布的公共日行情版本对应。日期不存在、非交易日或源数据不完整时，命令会失败，而不是生成部分分析结果。

### 3.4 失败、退出码和锁

所有数据命令使用统一的执行契约：

1. 为本次运行记录开始事件；
2. 对 `(模块, 数据集)` 取得排他锁；
3. 获取、校验并准备完整数据；
4. 仅在可以发布时写入正式数据版本；
5. 记录结束事件，释放锁。

命令失败会返回非零退出码。crontab 中应据此识别失败。若同一数据集已有运行中的同步，第二次执行会以如下错误退出：

```text
A synchronization for this dataset is already running.
```

不要为了绕过这个保护同时启动同一数据集的两个命令。先确认前一个进程是否仍在运行；若进程已异常退出，再谨慎检查锁目录和日志。

### 3.5 完整快照与旧数据保留

发布型命令不会把不完整抓取结果当作新版本发布。上游失败或数据不完整时：

- 新命令失败；
- 已经成功发布的旧版本保留；
- 对应前端/API 可继续读取旧缓存或旧数据库数据；
- 没有任何旧版本时，前端会显示“准备中”或空状态。

这意味着管理命令是**预计算路径**，不是让 Web API 在请求中完成全市场同步的机制。

### 3.6 进度日志

长耗时命令（行业快照、日行情、股票主数据、资金流）在开始事件和结束事件之间会持续输出进度行，
避免出现“命令还在跑但看不出在干什么”的情况。所有进度行使用同一个事件名 `data_command_progress`，
并带 `stage`、`processed`、`total`、`percent`、`eta_seconds`、`elapsed_seconds` 等字段：

```text
data_command_progress module=core dataset=stock_daily_prices business_date=2026-09-08 batch_id=... dry_run=False stage=stock_daily_prices phase=fetch processed=1200 total=5012 percent=23.9 eta_seconds=612.400 stock=000001
```

要看进度只需过滤这一个事件名：

```bash
python manage.py sync_stock_daily_prices --date 2026-09-08 2>&1 | grep data_command_progress
```

约定：

- 默认每 30 秒最多一行；**阶段开始**与**阶段结束**各强制输出一行，所以每个命令至少能看到“在做什么”和“做完了什么”；
- `processed` / `total` / `percent` / `eta_seconds` 只在能确定总量的循环里出现；
- 进度行与开始/结束行共用同一个 `batch_id`，可以据此把一次运行的所有输出聚在一起；
- 直接调用服务层代码（单元测试、API 请求路径）不会产生进度行，只有通过管理命令运行才有输出。

### 3.7 应用与访问日志

除进度行外，命令与服务层还会输出**业务事件行**：事件名在行首，后面是 `key=value` 字段（字段值已脱敏、单行渲染，可直接 `grep`）。

```text
2026-09-12 22:08:27,928 WARNING core.auth request_id=- login_rejected username=nobody
2026-09-12 22:08:27,929 INFO core.request request_id=d0cb... http_request method=POST path=/api/core/login/ status=401 duration_ms=100.100 user=anonymous
```

三组环境变量控制输出，改完 `.env` 重启即生效，**不必改代码**：

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `DATA_COMMAND_LOG_LEVEL` | `INFO` | 管理命令（含进度行）的级别。 |
| `DJANGO_LOG_LEVEL` | `INFO` | 应用与 Web 访问日志的级别；生产只想留问题时设 `WARNING`。 |
| `DJANGO_LOG_FORMAT` | `plain` | `plain` = 人读单行；`json` = 每行一个 JSON 对象，交给采集器。 |
| `DJANGO_REQUEST_LOG_SLOW_MS` | `1000` | 请求耗时超过该毫秒数记 `WARNING http_request_slow`。 |

生产只看问题时：

```bash
DJANGO_LOG_LEVEL=WARNING DATA_COMMAND_LOG_LEVEL=WARNING python manage.py sync_stock_daily_prices --date 2026-09-08
```

值得记住的事件名（排查读路径问题主要看这几个）：

- `read_generated` —— 该交易日本地没有派生结果，**在本次请求中现算并落库**。这是设计行为，但它解释了“只是打开页面为什么慢”；
- `read_stale_fallback`（`WARNING`）—— 目标日期算不出来，**退回了最近可用的旧数据**，页面此时会显示“正在展示旧数据”；
- `read_unavailable`（`WARNING`）—— 读路径整体失败；API 通常返回 404/202，日志里能看到具体原因；
- `upstream_retry` / `upstream_failed` —— 上游重试与最终失败；上游成功调用只记 `DEBUG`，避免一次同步几千行；
- `http_request_slow`（`WARNING`）—— 请求耗时超阈值，`duration_ms` 直接给出数字。

Web 请求的每个响应都带 `X-Request-ID` 头（若入站已带同名合法头则沿用），把该值粘到日志检索里即可串起这次请求产生的所有行。

---

## 4. 首次部署与数据初始化

### 4.1 初始化目标

首次部署时，数据库没有公共股票数据。需要先建表，再获取公共基础数据，最后构建业务模块数据。公共日行情初始化只用于把**截至初始化当天的最近一年**前复权日行情写入数据库；它不是日常任务。

### 4.2 建表与管理员账户

```bash
cd <repo>/backend

python manage.py migrate --database=default
python manage.py migrate --database=kaipanla
python manage.py migrate --database=stock_moves
python manage.py migrate --database=sector_momentum
python manage.py migrate --database=hundred_day

python manage.py check
python manage.py createsuperuser
```

管理员可通过 `/admin/` 查看公共数据版本、模块运行状态和模块数据；管理后台不用于在线启动或重跑采集命令。

### 4.3 推荐首次初始化顺序

> 以下命令会访问上游。请先确认 `.env`、网络和磁盘空间；尤其是日行情初始化会为全市场股票写入约一年的交易日记录，耗时明显长于其他命令。

```bash
cd <repo>/backend

# 1. 公共引用数据
python manage.py sync_trading_calendar
python manage.py sync_stock_master

# 2. 板块和行业内股票关系
python manage.py sync_kaipanla_industry_snapshot

# 3. 一次性导入最近一年的公共前复权日行情
python manage.py init_stock_daily_prices --years 1

# 4. 拉取开盘啦板块资金流；盘后、午休或非交易日须加 --latest
python manage.py fetch_kaipanla_sector_fund_flow --latest

# 5. 用同一交易日的本地公共数据构建三个盘后模块
python manage.py build_stock_moves --date YYYY-MM-DD
python manage.py build_sector_momentum --date YYYY-MM-DD
python manage.py build_hundred_day --date YYYY-MM-DD
```

最后三个构建命令使用的 `YYYY-MM-DD`，应替换成最近一个已经通过 `sync_stock_daily_prices` 或初始化导入成功的交易日。首次初始化结束时，它通常是当前最近交易日，而不应机械使用自然日。

### 4.4 日行情初始化与校正

```bash
python manage.py init_stock_daily_prices --years 1
```

此命令会重新抓取整年窗口，**与本地逐条比对后只写入有差异的行**，因此可以安全重跑：

- 用来填充或校正截至执行日期最近一年的公共日行情；
- 数据库为空时是首次导入；已有数据时只更新与上游不一致的行、补齐缺失的行；
- 与上游逐条一致时不发布新数据版本，也不会改动任何行；
- 不应放入 crontab；之后每天只执行 `sync_stock_daily_prices --date YYYY-MM-DD`；
- 不应由 Web API 触发；
- 如果失败，先阅读错误并修复根因，再重新执行；不要同时重复启动多个初始化进程。

当前默认值为 `--years 1`。除非数据保留策略改变，不要扩大年数；更大的时间范围会显著增加上游请求数、运行时间和 SQLite 文件体积。

---

## 5. 公共基础数据命令（`core`）

这些命令写入 `core` 数据库，是三个盘后分析模块共同依赖的基础。业务模块之间不互相调用，但它们会基于公共数据版本读取数据。

### 5.1 同步交易日历：`sync_trading_calendar`

```bash
python manage.py sync_trading_calendar [--dry-run]
```

**用途**：同步最近一年的 A 股交易日历，为交易日判定、盘中采集限制和日期校验提供基础数据。

**示例**：

```bash
python manage.py sync_trading_calendar
python manage.py sync_trading_calendar --dry-run
```

**前置条件**：

- `.env` 中 Hithink 数据源配置有效；
- `default` 数据库已迁移。

**写入位置**：`core` 数据库中的交易日数据及其数据版本/运行状态。

**是否可重复执行**：可以。建议在首次部署、跨年或交易日判断出现异常时执行；日常执行频率可低于日行情同步。

**成功输出形态**：

```text
synchronized <N> trading days.
```

**失败后处理**：检查 API Key、网络、上游配额和 `.env`。若失败，不应把当天非交易日/交易日结论仅依赖猜测；开盘啦资金流默认模式会使用已存在的交易日数据进行交易时段判断。

---

### 5.2 同步股票主数据：`sync_stock_master`

```bash
python manage.py sync_stock_master [--limit PAGE_SIZE] [--dry-run]
```

**用途**：同步公共 A 股股票列表，为日行情抓取和股票展示提供股票代码主数据。

**参数**：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--limit PAGE_SIZE` | `1000` | 单页获取的股票数。通常保持默认值；排查分页问题时可临时调小。 |
| `--dry-run` | 关闭 | 读取并校验数据但不发布。 |

**示例**：

```bash
python manage.py sync_stock_master
python manage.py sync_stock_master --limit 500 --dry-run
```

**前置条件**：Hithink 数据源配置有效，`default` 数据库已迁移。

**下游依赖**：`init_stock_daily_prices` 和 `sync_stock_daily_prices` 依赖可用的股票主数据。首次初始化必须先完成本命令。

**是否可重复执行**：可以。建议在首次初始化前执行；之后可在需要更新股票列表时运行。

**成功输出形态**：

```text
synchronized <N> stock records.
```

---

### 5.3 同步开盘啦行业—股票快照：`sync_kaipanla_industry_snapshot`

```bash
python manage.py sync_kaipanla_industry_snapshot [--dry-run]
```

**用途**：按开盘啦数据链路获取并发布行业关系：

```text
行业 → 行业股票列表
```

**存储模型**：每条行业记录包含三项业务字段：

1. 行业代码；
2. 行业名称；
3. 股票代码列表。

**当前使用范围**：供板块动量、百日新高新低占比等分析与展示使用。同一股票可以出现在多个行业的股票列表里，统计时在每个所属行业中分别计入。

**示例**：

```bash
python manage.py sync_kaipanla_industry_snapshot
python manage.py sync_kaipanla_industry_snapshot --dry-run
```

**前置条件**：

- `.env` 中开盘啦历史行业端点及相关参数可用；
- `default` 数据库已迁移；
- 不要求 `KPL_DEVICE_ID`、`KPL_USER_ID`、`KPL_TOKEN` 一定有值。

**请求日期（重要）**：开盘啦历史行业端点只服务交易日，对周末、节假日等没有交易的日期会返回 `errcode 1020 参数出错`。因此 `Date` 参数默认取**最近一个交易日**（同花顺交易日历优先，日历未覆盖时用法定节假日表回退到最近的工作日），而不是运行当天的本地日期。需要回补某一天时用 `.env` 的 `KAIPANLA_INDUSTRY_DATE` 显式指定。发布版本的 `business_date` 记录的是这个实际请求的交易日，与命令行输出一致。

**运行时长**：耗时几乎全部落在“按行业取成分股”这一步——每个行业至少要一次请求（用来确认该行业只有这一页），所以请求数主要由**行业数量**决定，不是把每页调大就能线性变快。当前启用的是 881xxx 行业族，共 104 个行业，因此成分股请求量约为“行业数 × 每行业页数”，另加行业列表分页；`KAIPANLA_INDUSTRY_STOCK_PAGE_SIZE=300` 已把大行业的页数压到很低。运行中可用 `data_command_progress` 行确认是否在推进（见 3.6）。

**分页参数（实测结论）**：

| 参数 | 取值 | 依据 |
| --- | --- | --- |
| `KAIPANLA_INDUSTRY_STOCK_PAGE_SIZE` | `300` | 实测该端点的 `st` 没有实际上限：`st=1000`、`10000` 仍返回该行业全量（通信 749 只），且 `st=300` 分页去重后与单页结果完全一致（3 页 → 749），说明“取不满即末页”的收敛判断在大页下依然成立。按新值对真实上游复测过三个最大板块（2291 / 2263 / 1973 只），取回结果与已发布快照逐只一致、无重复：2291 只只用了 8 次请求，而 30 只/页需要 77 次。整体成分股分页请求压到原来的三成到四成。 |
| `KAIPANLA_INDUSTRY_PARENT_PAGE_SIZE` | `30`（不要调大） | 板块列表端点的 `st` 有约 70 的隐性上限：`st≤70` 正常返回，`st≥75` 会**静默返回空列表**。空列表会被客户端当成“分页结束”，导致板块被静默截断——这是调大分页时最容易踩的坑。 |

**发布行为**：只在行业和股票关系能够组成完整快照时，才整体替换正式行业快照。失败时保留旧快照。

**下游依赖**：`build_sector_momentum`、`build_hundred_day` 依赖完整的板块快照版本。建议每次首次盘后构建前先完成此命令，或确认当前快照仍可用。

**成功输出形态**：

```text
synchronized <N> industry records.
```

---

### 5.4 初始化并校正最近一年日行情：`init_stock_daily_prices`

```bash
python manage.py init_stock_daily_prices [--years YEARS] [--dry-run]
```

**用途**：抓取全市场股票最近一年的公共前复权日行情，**与本地逐条比对后只写入有差异的行**。数据库为空时它就是首次导入；已有数据时它是校正与补齐，不会因为“本地已有数据”而报错或跳过。

**参数**：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--years YEARS` | `1` | 回溯年数。当前需求固定为最近 1 年，应使用默认值或显式传入 `1`。 |
| `--dry-run` | 关闭 | 抓取并与本地比对，只报告差异数量；不发布数据，也不改变数据集运行状态。 |

**标准用法**：

```bash
python manage.py init_stock_daily_prices --years 1
python manage.py init_stock_daily_prices --years 1 --dry-run
```

**前置条件**：

1. 已执行 `sync_trading_calendar`；
2. 已执行 `sync_stock_master`；
3. `.env` 中 Hithink 数据源 API Key、超时、限速和重试配置有效；
4. `backend/data/` 有足够磁盘空间，且部署账户可写；
5. 当前没有其他 `stock_daily_prices` 同步命令运行。

**行为约定**：

1. 每次都重新抓取整年窗口，不会因为本地已有数据而跳过或报错；
2. 比对只覆盖业务字段（前收、开高低收、涨跌幅、成交量、成交额、是否有成交）；`source_batch_id` / `source_data_version` 每次运行都不同，不参与比对；
3. 本地缺失的行视为“有差异”，所以重跑也能补齐一次中断导入留下的缺口；
4. 有差异时受影响的交易日**整体**改归属到新版本（读路径按 `source_data_version` 过滤，只刷新变化行会让同一交易日其余行读不到）；无差异时不发布新版本，避免下游派生分析因版本号变化而全量重建。

**不能把它当“补当天数据”的方式**：日常增量仍用下一节的单日同步命令。它也不应由 Web API 触发，或与其他 `stock_daily_prices` 命令并发（同一数据集有文件锁）。

**成功输出形态**：

```text
initialized <交易日数> trading days and <记录数> daily-price records.
updated <变化数> of <总数> daily-price records across <交易日数> trading days (<未变化数> unchanged).
no changes: <总数> daily-price records for <交易日数> trading days already match upstream.
dry-run: would initialize <交易日数> trading days and <记录数> daily-price records.
dry-run: would update <变化数> of <总数> daily-price records across <交易日数> trading days.
dry-run: <总数> daily-price records for <交易日数> trading days already match upstream; nothing to update.
```

**失败后处理**：

- 保留原始终端输出和命令日志；
- 检查 API Key、上游频率、网络和磁盘空间；
- 修复后重新运行同一命令（重跑只会写入有差异的行，不会重复导入）；
- 不要删除现有 SQLite 文件或缓存来“重试”，除非已经明确确认数据恢复策略。

---

### 5.5 同步某一交易日的日行情：`sync_stock_daily_prices`

```bash
python manage.py sync_stock_daily_prices --date YYYY-MM-DD [--dry-run]
```

**用途**：获取并发布某一个交易日的全市场公共前复权日行情。该命令是日常 crontab 应使用的日行情命令。

**示例**：

```bash
python manage.py sync_stock_daily_prices --date 2026-09-08
python manage.py sync_stock_daily_prices --date 2026-09-08 --dry-run
```

**前置条件**：

- 该日期为已知 A 股交易日；
- 股票主数据已可用；
- 该交易日的上游收盘数据已经实际可获取；
- Hithink 数据源配置有效。

**建议执行时间**：用户已确认盘后数据按实际收盘时间 **15:00（Asia/Shanghai）之后**处理。为给上游数据落地留出缓冲，生产 crontab 可安排在 15:05 或更晚；不要在 15:00 前运行。

**下游依赖**：同一 `--date` 的 `build_stock_moves`、`build_sector_momentum`、`build_hundred_day` 都依赖本命令成功发布的完整日行情版本。

**成功输出形态**：

```text
synchronized <N> daily-price records for YYYY-MM-DD.
```

**失败后处理**：不要继续构建相同日期的派生分析。先修复并重试该日期的日行情同步；成功后再按第 7 节的顺序执行三个构建命令。

---

### 5.6 盘中刷新当天全市场行情：`refresh_intraday_quotes`

```bash
python manage.py refresh_intraday_quotes [--date YYYY-MM-DD] [--dry-run]
```

**用途**：用全市场实时行情快照刷新"当天"的公共日行情，让交易时段内能每半小时看到当天最新数据。省略 `--date` 时使用服务器 Asia/Shanghai 的今天。

它与 `sync_stock_daily_prices` 写的是**同一个数据集**（`stock_daily_prices`）、同一套字段语义，差别只在通道和运行时机：

| | `sync_stock_daily_prices` | `refresh_intraday_quotes` |
| --- | --- | --- |
| 上游端点 | `/api/a-share/prices/historical`，逐只股票一次请求 | `/api/a-share/prices/snapshot`，全市场分页（约 6 页） |
| 典型耗时 | 约 6 分钟（五千余只） | 约 2 秒 |
| 运行时机 | 交易日 15:00 之后 | 交易时段内每 30 分钟 |
| 定位 | 收盘后的权威口径 | 盘中近似口径，收盘后由上面的命令纠正 |

**盘中口径的已知差异**（收盘后的 `sync_stock_daily_prices` 会一并纠正）：

- `volume` / `turnover` 低位有上游舍入，相对量级约 `1e-7`；
- 涨跌幅一律用**库内上一交易日的收盘价**重算，不采用快照的 `price_change_ratio_pct` —— 除权除息日上游给的是未复权前收口径；
- 停牌股（快照 `last_price` 为 null）落为 `has_valid_trade=False`，价格与成交量全部留空，不会把上游的 0 写成"成交过"；
- 本地没有上一交易日收盘价时（新股上市、复牌首日）涨跌幅留空；
- 覆盖率低于 `INTRADAY_QUOTE_MIN_COVERAGE_RATIO`（默认 0.95）时整轮作废，绝不把半截数据发布成"完整"版本。

**示例**：

```bash
python manage.py refresh_intraday_quotes --date 2026-09-11
python manage.py refresh_intraday_quotes --dry-run
```

**成功输出形态**：

```text
refreshed <N> intraday records (<M> unchanged) for YYYY-MM-DD from <K> quotes.
intraday quotes for YYYY-MM-DD are already up to date.
```

**下游影响**：盘中每次发布新版本都会让三个派生模块（个股异动 / 板块动量 / 百日新高）的输入版本变化，页面会按需重算当天结果。`scripts/intraday_orchestrator.sh quotes` 会在刷新成功后主动重建它们，页面因此不需要等待现场计算。

**默认入口的日期闸门**：当天 15:00 之前，`latest_eligible_trading_day` 按"当日是否已收盘"退回上一个交易日。只要当天已经发布过完整版本，读路径就把上限放宽到当天，页面默认入口因而跟随当天；当天还没有盘中版本时（例如 09:30 前）行为不变。

---

## 6. 开盘啦板块资金流命令（`kaipanla`）

### 6.1 获取完整板块资金流快照：`fetch_kaipanla_sector_fund_flow`

```bash
python manage.py fetch_kaipanla_sector_fund_flow [--latest] [--dry-run]
```

**用途**：抓取开盘啦板块资金流分页数据，并且只在所有分页能形成完整快照时发布到 `kaipanla` 数据库。

**参数**：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--latest` | 关闭 | 允许在午休、收盘后、开盘前或非交易日运行。它不是“请求历史时点”的参数；抓取仍是上游当前返回的数据，快照时间由本地运行时间对齐。 |
| `--dry-run` | 关闭 | 抓取并校验完整性，不写入正式快照。 |

**默认交易时段限制**：不带 `--latest` 时，仅允许在已同步交易日历认定的 A 股盘中运行：

```text
09:30–11:30（含）
13:00–15:00（含）
```

午休、收盘后、开盘前、周末、非交易日都会被拒绝。此时若确实需要取最新可得数据，请显式使用 `--latest`。

**示例**：

```bash
# 盘中定时快照
python manage.py fetch_kaipanla_sector_fund_flow

# 午休、收盘后、非交易日或人工补抓
python manage.py fetch_kaipanla_sector_fund_flow --latest

# 仅验证当前响应是否完整，不发布
python manage.py fetch_kaipanla_sector_fund_flow --latest --dry-run
```

**快照时间规则**：

- 盘中：归属到当前所在的 5 分钟槽；
- 午休：归属到 `11:30`；
- 收盘后：归属到 `15:00`；
- 非交易日或开盘前：归属到最近交易日的 `15:00`。

因此，`--latest` 仅放宽运行窗口，不会向上游传入历史快照时间参数。

**前置条件**：

- 已成功同步交易日历（默认盘中模式需要它判定交易日）；
- `.env` 中 `KAIPANLA_API_URL`、分页和超时配置有效；
- `kaipanla` 数据库已迁移；
- `KPL_*` 凭据可为空，也可按 `.env` 配置提供。

**成功输出形态**：

```text
published <N> Kaipanla sector fund-flow records.
```

**失败与降级**：

如果遇到上游 403、429、超时、屏蔽、分页不完整或空结果，命令会失败且不会发布半份新快照。旧快照保留；若从未成功发布过快照，开盘啦前端页面可显示准备中或空状态，其他三个业务模块不受影响。

---

## 7. 盘后派生分析命令

三个命令都只读本地公共数据并写入各自独立业务数据库；它们不应主动访问外部数据源。三个命令必须使用同一个已成功发布的交易日日期。

共同前置条件：

1. `sync_stock_daily_prices --date YYYY-MM-DD` 已成功；
2. 对需要行业关系的模块，`sync_kaipanla_industry_snapshot` 已有完整快照；
3. 对应业务数据库已迁移；
4. 选择的日期是实际交易日，且本地公共日行情版本完整。

**与 Web 按需生成的关系**：这三个命令是批量路径，crontab 应当继续按交易日调用它们。同时，三个模块的 API 读取路径在"该日期已有完整本地公共数据、但缺派生结果"时会当场用同一套 analysis + writer 生成该日期的结果并落库，因此命令与 API 生成的是**同一种产物**，不会互相产生重复或冲突记录（同一 `business_date + source_*_version` 走 `update_or_create`，且由 `dataset_lock` 互斥）。这意味着：漏跑某一天的构建命令不会让页面空白，但批量命令仍然是保证数据在盘后第一时间可用的正常链路，不要把 API 当成调度器使用。生成只读本地数据，绝不访问上游。

### 7.1 构建大涨跌幅与大成交量个股：`build_stock_moves`

```bash
python manage.py build_stock_moves --date YYYY-MM-DD [--dry-run]
```

**用途**：为指定交易日构建“大涨跌幅与大成交量个股”结果，含上证、深证、北交所各自的涨跌两组，共六组。

**示例**：

```bash
python manage.py build_stock_moves --date 2026-09-08
python manage.py build_stock_moves --date 2026-09-08 --dry-run
```

**写入位置**：`stock_moves` SQLite 数据库。

**成功输出形态**：

```text
built <N> stock-move records for YYYY-MM-DD.
```

**失败后处理**：优先检查同日公共日行情是否完整。不要通过重复运行来绕过缺失的基础数据；基础日行情成功后再重试。

### 7.2 构建板块动量：`build_sector_momentum`

```bash
python manage.py build_sector_momentum --date YYYY-MM-DD [--dry-run]
```

**用途**：使用指定交易日的本地公共日行情和开盘啦**板块**股票关系，生成板块动量排名。

**示例**：

```bash
python manage.py build_sector_momentum --date 2026-09-08
python manage.py build_sector_momentum --date 2026-09-08 --dry-run
```

**写入位置**：`sector_momentum` SQLite 数据库。

**成功输出形态**：

```text
built <N> sector-momentum records for YYYY-MM-DD.
```

**特别说明**：行业关系取自 `core` 的行业快照。行业关系缺失或公共日行情版本不完整时会失败，而不是使用跨模块临时调用或不完整数据凑出结果。

### 7.3 构建百日新高新低占比：`build_hundred_day`

```bash
python manage.py build_hundred_day --date YYYY-MM-DD [--dry-run]
```

**用途**：使用本地公共日行情和板块股票关系，生成指定交易日的百日新高、新低及相关行业汇总结果。

**示例**：

```bash
python manage.py build_hundred_day --date 2026-09-08
python manage.py build_hundred_day --date 2026-09-08 --dry-run
```

**写入位置**：`hundred_day` SQLite 数据库。

**成功输出形态**：

```text
built <N> hundred-day records for YYYY-MM-DD.
```

**特别说明**：百日窗口依赖历史日行情。首次部署没有完成最近一年初始化，或者中间存在缺失交易日时，不能期待该命令产出可信的百日统计；应先恢复公共日行情数据。

---

## 8. Django 运维与诊断命令

以下是 Django 自带但本项目部署中常用的管理命令。

### 8.1 配置自检

```bash
python manage.py check
```

适用于修改 `.env`、迁移、升级依赖、上线前和故障排查前。出现错误时先修复配置或应用注册问题，再执行数据同步。

### 8.2 迁移

```bash
# 查看是否存在未生成的模型迁移；不会实际创建迁移文件
python manage.py makemigrations --check --dry-run

# 分库迁移
python manage.py migrate --database=default
python manage.py migrate --database=kaipanla
python manage.py migrate --database=stock_moves
python manage.py migrate --database=sector_momentum
python manage.py migrate --database=hundred_day
```

不要在生产环境因数据命令报错就盲目执行 `makemigrations`。只有代码中确实有模型变更且迁移文件经过评审时，才生成和提交新迁移。

### 8.3 创建或修改管理员账户

```bash
python manage.py createsuperuser
python manage.py changepassword <username>
```

完成后通过 Django 管理后台查看数据版本、运行状态和业务数据。不要把管理员密码放进 shell 历史、crontab 或文档。

### 8.4 启动本地开发服务

```bash
python manage.py runserver 127.0.0.1:8000
```

本地前端运行在 `http://localhost:5173/` 时，浏览器请求 `/api/...` 会先发送到 Vite，再由 `VITE_DEV_BACKEND_ORIGIN=http://127.0.0.1:8000` 转发给 Django。生产环境应通过 HTTPS 反向代理同源提供前端与 `/api/`，而不是使用 Django 开发服务器。

### 8.5 测试

```bash
python manage.py test
```

数据采集命令失败的修复、模型变更或服务逻辑调整后，应至少运行相关测试；完整回归使用上面的全量测试命令。

---

## 9. 推荐的 crontab 执行策略

### 9.1 原则

- 所有时间以 `Asia/Shanghai` 为准；服务器时区也应保持一致。
- 全市场近一年初始化命令不进入 crontab。
- 盘后派生分析只能在同日公共日行情成功后运行。
- 某个业务模块失败不能阻断其他独立模块。
- 开盘啦资金流与盘后日行情/分析是不同数据集，可以独立调度。
- crontab 内使用绝对路径、明确的虚拟环境 Python、日志重定向和 `flock`/项目内锁保护。

### 9.2 盘中编排（推荐直接使用仓库内脚本）

仓库提供了一段编排脚本，覆盖“交易日历 + 5 分钟板块资金流 + 30 分钟全市场行情”：

```bash
scripts/intraday_orchestrator.sh calendar   # 同步交易日历（每个交易日开盘前一次）
scripts/intraday_orchestrator.sh fundflow   # 抓一次开盘啦板块资金流快照
scripts/intraday_orchestrator.sh quotes     # 刷新当天全市场行情并重建三个派生模块
```

脚本自己判断是否落在交易时段（09:30-11:30 / 13:00-15:00）：时段外直接以 0 退出并只写一行日志，不产生失败告警。`quotes` 只在行情刷新成功后重建派生模块，避免用同一份旧输入白算一遍；模块开关跟随 `.env` 的 `ENABLED_MODULES`。运行日志按天落在 `backend/data/intraday-logs/YYYY-MM-DD.log`。

**交易日历必须先到位**：盘中命令都要求 `TradingDay` 里能查到"今天"，所以每个交易日开盘前要跑一次 `calendar`（脚本已包含）。

如果希望在盘后手工或定时补一次最近快照，使用：

```bash
python manage.py fetch_kaipanla_sector_fund_flow --latest
```

#### 9.2.1 安装调度（macOS 推荐 launchd）

```bash
scripts/install_intraday_launchd.sh install
scripts/install_intraday_launchd.sh status
scripts/install_intraday_launchd.sh uninstall
```

装载三个用户级代理：`calendar` 在工作日 09:25 执行，`fundflow` 每 5 分钟、`quotes` 每 30 分钟轮询一次（时段外由脚本自行跳过）。

> macOS 上 `/usr/bin/crontab` 受 TCC 保护，非交互 shell 写入会报 `Operation not permitted`；用户级 launchd 代理不需要额外授权。但两者都必须在**你自己的登录会话**（Terminal.app）里执行 —— 自动化/沙箱 shell 会被 launchd 拒绝（`Bootstrap failed: 5: Input/output error`）。

#### 9.2.2 备选：crontab

```bash
scripts/install_intraday_cron.sh install
scripts/install_intraday_cron.sh show
scripts/install_intraday_cron.sh uninstall
```

它写入一个带标记的块（`<venv-python>` 为安装时探测到的解释器绝对路径，可被 `PYTHON_BIN` 覆盖）。下面块首尾两行的标记串是 `scripts/install_intraday_cron.sh` 里的固定常量，脚本靠 `awk` 用它定位并删除自己写入的条目，**不要手改**（改了之后 `uninstall` 就找不到旧块）：

```cron
# >>> market-review intraday >>>
25 9 * * 1-5 cd <repo> && PYTHON_BIN=<venv-python> <repo>/scripts/intraday_orchestrator.sh calendar
*/5 9-11,13-14 * * 1-5 cd <repo> && PYTHON_BIN=<venv-python> <repo>/scripts/intraday_orchestrator.sh fundflow
0 15 * * 1-5 cd <repo> && PYTHON_BIN=<venv-python> <repo>/scripts/intraday_orchestrator.sh fundflow
0,30 9-11,13-14 * * 1-5 cd <repo> && PYTHON_BIN=<venv-python> <repo>/scripts/intraday_orchestrator.sh quotes
0 15 * * 1-5 cd <repo> && PYTHON_BIN=<venv-python> <repo>/scripts/intraday_orchestrator.sh quotes
# <<< market-review intraday <<<
```

> **标记串 2026-09-13 改过一次**（旧串里带项目目录名）。清理逻辑按「形状」匹配而不是按字面值匹配（`# >>> … intraday >>>` / `# <<< … intraday <<<`），所以**旧串写下的块同样能被识别并删除**：在改名前装过 crontab 的机器上直接重跑一次 `scripts/install_intraday_cron.sh install` 即可，脚本会先清掉旧块再写入新块，不需要手工编辑 crontab。

> 这些条目只做时间调度，真正的交易日判定（节假日、非交易日）由 Django 命令自己完成，所以用最朴素的“周一到周五 + 时段”表达式即可。cron 的 `PATH` 很窄，因此解释器用绝对路径内联在每条命令里，而不是写成 cron 的环境变量行 —— 后者会污染标记块之后用户自己的条目。

#### 9.2.3 不使用脚本时的等价手工命令

```bash
# 盘中每 5 分钟
python manage.py fetch_kaipanla_sector_fund_flow

# 盘中每 30 分钟
day="$(TZ=Asia/Shanghai date +%F)"
python manage.py refresh_intraday_quotes --date "$day"
python manage.py build_stock_moves --date "$day"
python manage.py build_sector_momentum --date "$day"
python manage.py build_hundred_day --date "$day"
```

#### 9.2.4 前端的自动刷新

四个页面在交易时段内会自动重取：板块资金流每 5 分钟，其余三页每 30 分钟；非交易时段不轮询，手选了历史日期也不轮询。数据拉取时间显示在各页状态区的“更新于 HH:MM”。前端的时段判断只看周一到周五的连续竞价时段，节假日多轮询几次只会拿到同样的数据，真正的交易日判定在后端。

### 9.3 每日盘后任务示例

以下为一个安全、按依赖顺序的示例。选择 15:10 只是缓冲建议；若上游实际落地较慢，应延后执行，而不是在数据未就绪时反复触发。

```cron
# 15:10 后先同步当天日行情。日期由服务器的 Asia/Shanghai 当天生成。
10 15 * * 1-5 cd /srv/<deploy-dir>/backend && <venv-python> manage.py sync_stock_daily_prices --date "$(date +\%F)" >> /srv/<deploy-dir>/backend/logs/daily-prices.log 2>&1

# 只有上一步成功时才继续构建三个派生模块。使用同一个日期。
20 15 * * 1-5 cd /srv/<deploy-dir>/backend && <venv-python> manage.py build_stock_moves --date "$(date +\%F)" >> /srv/<deploy-dir>/backend/logs/stock-moves.log 2>&1
25 15 * * 1-5 cd /srv/<deploy-dir>/backend && <venv-python> manage.py build_sector_momentum --date "$(date +\%F)" >> /srv/<deploy-dir>/backend/logs/sector-momentum.log 2>&1
30 15 * * 1-5 cd /srv/<deploy-dir>/backend && <venv-python> manage.py build_hundred_day --date "$(date +\%F)" >> /srv/<deploy-dir>/backend/logs/hundred-day.log 2>&1
```

> 上面的四条独立 cron 行**不会自动传播上一条的成功/失败状态**。若要严格保证“日行情成功后才构建”，应由单个 shell 脚本按 `&&` 串联，或由调度系统编排依赖。

推荐生产脚本结构如下（示意，替换实际 Python 和路径）：

```bash
#!/usr/bin/env bash
set -euo pipefail

project=/srv/<deploy-dir>/backend
python=/srv/<deploy-dir>/.venv/bin/python
trade_date="$(TZ=Asia/Shanghai date +%F)"

cd "$project"
"$python" manage.py sync_stock_daily_prices --date "$trade_date"
"$python" manage.py build_stock_moves --date "$trade_date"
"$python" manage.py build_sector_momentum --date "$trade_date"
"$python" manage.py build_hundred_day --date "$trade_date"
```

脚本返回非零时，应保留日志并在下一次运维检查时查看 Django 管理后台运行状态。当前需求不要求外部通知；不要因某次开盘啦或同花顺上游失败而自动破坏其他模块调度。

### 9.4 推荐频率概览

| 数据集/命令 | 推荐时机 | 是否应每日运行 |
| --- | --- | --- |
| `sync_trading_calendar` | 首次部署、跨年、交易日异常排查时 | 否；可按运维策略低频执行。 |
| `sync_stock_master` | 首次部署、股票清单变化时 | 否；按需。 |
| `sync_kaipanla_industry_snapshot` | 首次部署、行业关系需要刷新时 | 否；按需或低频。 |
| `init_stock_daily_prices --years 1` | 新环境首次部署、需要按上游校正历史日行情时 | 否；可安全重跑，与上游一致时不写任何行。 |
| `sync_stock_daily_prices --date` | 交易日 15:00 后，数据就绪时 | 是。 |
| `fetch_kaipanla_sector_fund_flow` | 盘中，每 5 分钟或按需 | 是（交易日盘中）。 |
| `refresh_intraday_quotes --date` | 交易时段内每 30 分钟 | 是（交易日盘中）。 |
| `build_stock_moves` | 日行情成功后（盘中刷新后也可重建当天） | 是（交易日）。 |
| `build_sector_momentum` | 日行情和行业快照可用后（盘中刷新后也可重建当天） | 是（交易日）。 |
| `build_hundred_day` | 日行情和行业快照可用后（盘中刷新后也可重建当天） | 是（交易日）。 |

---

## 10. 常见错误、恢复与排查

### 10.1 上游股票数据认证、限流或网络失败

**可能表现**：`sync_stock_master`、`sync_trading_calendar`、`init_stock_daily_prices` 或 `sync_stock_daily_prices` 非零退出。

**检查顺序**：

1. 确认从 `backend/` 运行，根目录 `.env` 存在且权限允许当前账户读取；
2. 检查 `HITHINK_FINANCE_BASE_URL`、`HITHINK_FINANCE_API_KEY`，不要把值打印到终端或提交到 Git；
3. 检查 `HITHINK_FINANCE_TIMEOUT_SECONDS`、`HITHINK_FINANCE_REQUEST_DELAY_SECONDS`、`HITHINK_FINANCE_MAX_RETRIES` 是否符合上游配额；
4. 使用同一命令的 `--dry-run` 验证问题是否可稳定复现；
5. 修复后从失败日期开始重跑，再执行依赖它的派生分析。

### 10.2 日行情初始化被中断

**原则**：初始化只应由一个进程运行。不要同时开两个终端重跑，也不要直接删除数据库作为第一反应。

**建议步骤**：

1. 等待或确认原进程已退出；
2. 查看 `backend/logs/`、终端输出和 Django 管理后台运行状态；
3. 检查磁盘空间、数据源请求错误和同步锁；
4. 修复根因；
5. 重新执行：

   ```bash
   python manage.py init_stock_daily_prices --years 1
   ```

6. 初始化成功后，用最近完整交易日重新构建三个派生分析。

### 10.3 开盘啦资金流只在盘中允许运行

**错误原因**：不带 `--latest` 的命令在午休、收盘后、开盘前、周末或非交易日执行。

**处理方式**：

```bash
python manage.py fetch_kaipanla_sector_fund_flow --latest
```

只在确实希望获得“此刻上游可返回的最新结果”时使用。该参数不会指定历史日期，也不会使开盘啦上游返回历史盘中数据。

### 10.4 开盘啦返回不完整、403、429 或超时

这是允许的独立失败模式。命令不应发布半份快照；前端优先展示旧版本，旧版本不存在时显示空/准备中。处理方法：

1. 检查本次命令日志和 `.env` 中的开盘啦 URL、超时、延迟、重试及可选 `KPL_*`；
2. 不要为了提高成功率而把 Token 写到脚本或日志；
3. 稍后重试，或等待下一个定时快照；
4. 不需要阻塞股票日行情和三个派生分析模块。

### 10.5 派生分析报“源数据版本不可用”或没有结果

最常见原因是运行顺序错误：日行情还未成功发布，或者行业关系快照缺失。

按以下顺序恢复：

```bash
python manage.py sync_stock_daily_prices --date YYYY-MM-DD
python manage.py sync_kaipanla_industry_snapshot
python manage.py build_stock_moves --date YYYY-MM-DD
python manage.py build_sector_momentum --date YYYY-MM-DD
python manage.py build_hundred_day --date YYYY-MM-DD
```

如果当日行业关系无需刷新且已有完整版本，则第二步无需重复执行。不要尝试让业务模块绕过公共数据版本直接访问远程数据源。

### 10.6 命令提示已有同步正在运行

**表现**：

```text
A synchronization for this dataset is already running.
```

**处理方式**：

1. 使用 `ps` 等系统命令确认先前命令是否还在运行；
2. 若仍在运行，等待其结束；
3. 若已异常退出，先保留相关日志，再检查 `backend/data/locks/` 的残留锁；
4. 仅在确认没有活跃进程时，按项目锁机制和运维流程清理异常状态；
5. 重新运行同一命令一次。

### 10.7 Web 页面没有立刻显示新数据

Web API 读取顺序为：文件缓存 → 本地数据库 → 有限的远程修复。命令成功后通常会使所属模块缓存失效，但浏览器仍可能有前端状态或请求时序影响。

**最快的一步是先看日志**（事件名见 §3.7）：若出现 `read_generated`，说明该交易日本来没有派生结果、页面这次是现算的，稍等即可；若出现 `read_stale_fallback`，说明目标日期算不出来、页面退回旧数据（页面会同时提示“正在展示旧数据”），这时问题在数据不在缓存；若只看到 `http_request_slow`，则确是计算慢而不是没更新。

排查顺序：

1. 确认命令已成功退出并输出 `published`、`synchronized`、`built` 或 `refreshed`；
2. 在 Django 管理后台确认数据版本/运行状态；
3. 盘中确认调度是否真的在跑：`scripts/install_intraday_launchd.sh status`，日志在 `backend/data/intraday-logs/YYYY-MM-DD.log`。页面在交易时段会自动重取（板块资金流每 5 分钟、其余三页每 30 分钟），非交易时段与手选历史日期时都不会轮询；
4. 刷新页面并重新登录（如 Session 已过期）；
5. 检查 API 实际访问的是正确环境；本地 Vite 请求显示为 `localhost:5173/api/...` 是代理入口，Django 后端应为 `127.0.0.1:8000`；
6. 不要通过删除 `backend/cache/` 作为常规刷新办法；
7. 从浏览器响应头取 `X-Request-ID`，在应用日志里检索该值，可看到这次请求依次经历了哪些读路径分支。

---

## 11. 数据库、缓存与运行状态

### 11.1 数据归属

| 类型 | 位置 | 说明 |
| --- | --- | --- |
| 公共引用数据、行业关系、公共日行情、数据版本与运行状态 | `core.sqlite3` | 基础库数据；三个盘后模块共同读取。 |
| 开盘啦资金流快照 | `kaipanla.sqlite3` | 独立模块数据。 |
| 大涨跌幅与大成交量个股结果 | `stock_moves.sqlite3` | 独立分析结果。 |
| 板块动量结果 | `sector_momentum.sqlite3` | 独立分析结果。 |
| 百日新高新低结果 | `hundred_day.sqlite3` | 独立分析结果。 |
| API 缓存 | `backend/cache/` | 可再生成的文件缓存，不是数据库备份。 |
| 命令锁 | `backend/data/locks/` | 防止相同数据集并发同步。 |

### 11.2 管理后台

使用 `createsuperuser` 创建的账户登录 `/admin/` 后，可检查：

- 公共数据版本是否为完整、成功状态；
- 业务模块最近一次运行是成功还是失败；
- 失败摘要；
- 每个业务数据库已发布的数据。

管理后台是状态观察和数据检查入口，不负责替代 crontab、shell 脚本或 `manage.py` 命令。

### 11.3 备份与清理

当前策略是**手动处理** SQLite 和文件缓存的备份、保留与清理。执行数据库替换、删除缓存或清理锁文件前：

1. 停止相关同步任务；
2. 备份目标 SQLite 文件；
3. 记录当前数据版本及最近成功日期；
4. 只操作确认无活跃任务的模块；
5. 修改后执行 `python manage.py check` 并验证对应 API/页面。

---

## 12. 命令速查表

| 命令 | 是否访问上游 | 主要依赖 | 是否日常执行 | 关键参数 |
| --- | --- | --- | --- | --- |
| `sync_trading_calendar` | 是 | Hithink 配置、`core` 数据库 | 按需/低频 | `--dry-run` |
| `sync_stock_master` | 是 | Hithink 配置、`core` 数据库 | 按需 | `--limit`、`--dry-run` |
| `sync_kaipanla_industry_snapshot` | 是 | 开盘啦行业端点、`core` 数据库 | 按需/低频 | `--dry-run` |
| `init_stock_daily_prices --years 1` | 是 | 交易日历、股票主数据、Hithink 配置 | 首次部署；之后按需校正 | `--years`、`--dry-run` |
| `sync_stock_daily_prices --date DATE` | 是 | 股票主数据、Hithink 配置 | 每个交易日盘后 | `--date`、`--dry-run` |
| `refresh_intraday_quotes [--date DATE]` | 是 | 股票主数据、Hithink 配置 | 每个交易日盘中每 30 分钟 | `--date`（默认今天）、`--dry-run` |
| `fetch_kaipanla_sector_fund_flow` | 是 | 交易日历、开盘啦配置、`kaipanla` 数据库 | 交易日盘中 | `--latest`、`--dry-run` |
| `build_stock_moves --date DATE` | 否 | 同日完整公共日行情 | 每个交易日盘后 | `--date`、`--dry-run` |
| `build_sector_momentum --date DATE` | 否 | 同日完整公共日行情、行业快照 | 每个交易日盘后 | `--date`、`--dry-run` |
| `build_hundred_day --date DATE` | 否 | 历史公共日行情、行业快照 | 每个交易日盘后 | `--date`、`--dry-run` |
| `check` | 否 | `.env` 和 Django 配置 | 部署/排查时 | Django 标准参数 |
| `migrate --database=...` | 否 | 对应 SQLite 路径可写 | 部署与模型升级时 | `--database` |
| `createsuperuser` | 否 | `default` 数据库 | 首次部署/账户管理 | 交互式输入 |
| `test` | 通常否 | 测试环境 | 代码变更后 | Django 标准参数 |

## 相关文档

- [部署与运行说明](deployment.md)：生产部署、环境变量、前端代理和更完整的部署恢复说明。
- [集成能力验证记录](../data-sources/hithink-and-kaipanla-capability.md)：股票 REST 与开盘啦行业关系能力的验证结果。
- [集成规格](../specs/integration-spec.md)：模块边界、数据契约和验收要求。
- [验收可追溯性](../acceptance/traceability.md)：规格到测试/验证证据的映射。
