# 部署与运行说明

> 本文适用于本地开发机和阿里云生产机。两者使用同一份代码；环境差异仅放在仓库根目录 `.env`，不修改 Python 或前端源码。本文中的 `/srv/<deploy-dir>` 是生产部署路径示例，需替换为实际绝对路径。

## 1. 首次部署前检查

1. 使用受支持的 Python 环境创建虚拟环境，并在 `backend/` 安装 `requirements.txt` 中的依赖。
   - 其中 `chinese-calendar` 是**交易日的唯一判定来源**（周末与法定节假日）。它**按年内置节假日数据**，每年国务院放假安排公布后需升级该包并重启服务；跨年未升级时，未覆盖年份会退化为「工作日即交易日」并对该年记一次 WARNING，不会中断采集。系统没有任何上游交易日历，也没有「同步交易日历」这一步。
   - 升级窗口是固定的：该包**每年只发一个覆盖次年的版本，时间在 10 月底至 11 月中**，紧随国务院公布次年安排之后。
   - 覆盖边界不用靠记性：`GET /api/core/health/` 的 `data.trading_calendar` 会给出 `covered_through` 和 `next_year_covered`，**`next_year_covered=false` 就是「该升级依赖了」**（见 `docs/ops/manage-commands.md` §5）。
   - **生产环境还需要一个 WSGI 服务器来常驻进程，它不在 `requirements.txt` 中**（本地开发用 `runserver`，用不着）。安装与启动方式见 §7。
2. 在 `frontend/` 安装锁定版本的依赖并运行 `npm run build`，生成 `frontend/dist/`。
3. 复制 `.env.example` 为根目录 `.env`；该文件不能提交到 Git，文件权限应仅允许部署账户读取（例如 `chmod 600 .env`）。
4. 创建并确保部署账户可写：

   ```bash
   mkdir -p backend/data backend/data/locks backend/cache backend/logs
   ```

   `backend/data/` 内保存五个 SQLite 文件，`backend/cache/` 保存文件缓存，锁目录为 `backend/data/locks/`。这些均为运行时数据，不提交到版本库。
5. 确认服务器时区为 `Asia/Shanghai`；同时将 `.env` 的 `DJANGO_TIME_ZONE=Asia/Shanghai` 保持不变。

## 2. `.env` 配置清单

以 `.env.example` 为唯一字段清单。生产环境至少需要检查以下分组：

| 分组 | 必填/关键字段 | 说明 |
| --- | --- | --- |
| Django | `DJANGO_SECRET_KEY`、`DJANGO_DEBUG=false`、`DJANGO_ALLOWED_HOSTS`、`DJANGO_TIME_ZONE` | 密钥使用随机长值；生产域名必须填写，不能使用 `*`。 |
| SQLite | 五个 `*_DATABASE_PATH` | 默认均放在 `backend/data/`，可改为可写的绝对路径。 |
| 缓存与锁 | `FILE_CACHE_*`、`LOCK_DIRECTORY` | 文件缓存与数据集互斥锁。**没有请求侧修复配置**：Web 请求不访问上游，抓取只发生在 crontab 拉起的命令里。 |
| 模块开关 | `ENABLED_MODULES` | 逗号分隔的静态模块列表；可独立关闭一个业务模块。 |
| 同花顺 REST | `HITHINK_FINANCE_*` | 只用于股票表、交易日和前复权日线；`HITHINK_FINANCE_API_KEY` 仅放在 `.env`。 |
| 开盘啦 | `KAIPANLA_*`、`KPL_*` | 用于板块资金流和行业→股票关系。`KPL_DEVICE_ID`、`KPL_USER_ID`、`KPL_TOKEN` 均可留空；空值不会作为字段发出，非空值才附带。凭据不能出现在日志或版本库。 |
| 浏览器安全 | `SESSION_COOKIE_*`、`CSRF_COOKIE_*`、`CSRF_TRUSTED_ORIGINS` | 生产 HTTPS 下保持 secure cookie 为 `true`，可信来源填写实际 `https://` 域名。当前版本按同源部署，不启用跨域 CORS。 |
| 日志 | `DJANGO_LOG_LEVEL`、`DJANGO_LOG_FORMAT`、`DJANGO_REQUEST_LOG_SLOW_MS`、`DATA_COMMAND_LOG_LEVEL` | 应用日志级别默认 `INFO`（生产只想留问题时设 `WARNING`）；格式 `plain`（单行 `key=value`）或 `json`（交给采集器）；请求超过该毫秒数升级为 `WARNING`，默认 `1000`。字段与事件约定见 `docs/ops/manage-commands.md` §3.7。 |
| 本地 Vite 代理 | `VITE_DEV_BACKEND_ORIGIN` | 仅本地开发使用。Vite 将浏览器的相对 `/api/` 请求代理到该 Django 地址，避免跨域 Session/CSRF Cookie 问题；生产静态部署不使用此项。 |

生产示例只表达结构，不包含真实值：

```dotenv
DJANGO_SECRET_KEY=replace-with-a-unique-random-production-secret
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=review.example.com
DJANGO_TIME_ZONE=Asia/Shanghai
CSRF_TRUSTED_ORIGINS=https://review.example.com
SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
# 日志：生产默认保留 INFO 的应用与访问日志；接入采集器时改为 json。
DJANGO_LOG_LEVEL=INFO
DJANGO_LOG_FORMAT=plain
DJANGO_REQUEST_LOG_SLOW_MS=1000
```

### 2.1 日志

后端日志分两路，都由环境变量控制、**无需改代码重启**：

- **管理命令日志**（`DATA_COMMAND_LOG_LEVEL`，默认 `INFO`）：`sync_*` / `refresh_*` / `fetch_*` / `build_*` 的批次与进度输出，见 `docs/ops/manage-commands.md` §3.6。
- **应用与访问日志**（`DJANGO_LOG_LEVEL`，默认 `INFO`）：`core` 与四个业务模块的业务事件、登录事件、以及每个 Web 请求的访问行。

访问日志每条一行，含 `request_id`（同一请求内的所有日志共享该 id，异常时可直接串起来看）、`method`、`path`、`status`、`duration_ms`、`user`。两个关键行为：

- **慢请求升级**：耗时 ≥ `DJANGO_REQUEST_LOG_SLOW_MS`（默认 1000ms）的请求记 `WARNING http_request_slow`。三个盘后模块的读路径会**在请求中按需生成本地派生结果**，一次几秒的计算必须能在日志里自己冒出来；
- **降噪**：`/static/`、`/favicon.ico`、`/api/core/health/` 只记 `DEBUG`；4xx 不重复升级（严重级别由 Django 自身的 `django.request` 负责）；上游批量调用的成功路径只记 `DEBUG`，避免一次同步几千行淹没日志。

`DJANGO_LOG_FORMAT=json` 时每行是一个 JSON 对象，`event` 与业务字段提升为顶层键，便于 ELK / Loki 之类的采集器直接解析。两种格式都**单行输出且已脱敏**（密钥、`token`/`password` 等字段会被替换，单字段超过 500 字符会截断），不会因换行或敏感值污染日志。

查看方式：

```bash
# 只看问题（沿用 §6 crontab 里 >> backend/logs/*.log 的重定向路径）
tail -f backend/logs/*.log | grep -E 'WARNING|ERROR'
# 只看 Web 访问行（需要单独收集时）
grep -E 'http_request' backend/logs/*.log
# 追一个请求产生的全部日志（request_id 取自响应头 X-Request-ID）
grep '<request_id>' backend/logs/*.log
```

## 3. 本地前后端联调

本地使用 Vite 时，浏览器中的请求地址会显示为 `http://localhost:5173/api/...`；这是开发代理入口，而不是由 Vite 提供业务 API。Vite 会把 `/api/` 转发到根目录 `.env` 中的 `VITE_DEV_BACKEND_ORIGIN`，本地默认值为 `http://127.0.0.1:8000`。这样 Django 接收到实际 API 请求，同时浏览器仍在同一前端来源保存和发送 Session、CSRF Cookie。

本地纯 HTTP 开发时，在本地 `.env` 中设置以下值（不能复制到生产环境）：

```dotenv
VITE_DEV_BACKEND_ORIGIN=http://127.0.0.1:8000
CSRF_TRUSTED_ORIGINS=http://localhost:5173
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
```

生产环境由 HTTPS 反向代理把前端与 `/api/` 放到同一公开域名下，因此不使用 Vite 代理，也必须保持两项 `*_COOKIE_SECURE=true`。

## 4. 初始化五个 SQLite 数据库

所有命令从 `backend/` 目录执行。路由器只允许 `core` 写入 `default`，每个业务 App 写入同名数据库。按下面顺序执行一次迁移；可安全重复执行。

```bash
python manage.py migrate --database=default
python manage.py migrate --database=kaipanla
python manage.py migrate --database=stock_moves
python manage.py migrate --database=sector_momentum
python manage.py migrate --database=hundred_day

python manage.py check
python manage.py createsuperuser
```

升级代码后同样要把这五条重跑一遍。`migrate` 不带 `--database` 只作用于 `default` 库，其余四个业务库不会被碰到：漏掉哪个库，它就会停在旧结构上（页面照常能读，因为读的是自己库里的表），新加的列不会出现、该删的旧表也还在。用 `python manage.py showmigrations --database=<库名>` 看哪些行还是 `[ ]`。

管理员通过 `/admin/` 查看公共数据及各模块已落库的结果；后台只读，不提供在线启动、停止或重跑采集命令，也不展示运行状态（那在命令日志里）。

## 5. 首次数据准备

在全新数据库中，按顺序执行：

```bash
python manage.py sync_stock_master
python manage.py sync_kaipanla_industry_snapshot
python manage.py init_stock_daily_prices --years 1
```

前两条各自幂等，重复执行只做增量同步。交易日不需要任何准备步骤：它由 `backend/core/services/calendar.py` 用 `chinese-calendar` 在本地推导。

`init_stock_daily_prices --years 1` 第一次执行会导入「以执行日为终点的最近一年」公共前复权日行情。**它不是一次性命令，之后可以也应该重跑**：第二次起会先逐条与上游比对，只写入有差异的行，是**按上游校正与补齐历史行情的官方手段**（`--dry-run` 会先报告将改动多少行；全部一致时输出 `no changes`）。不要因为"首次准备"这个标题而不敢重跑。它也是**唯一**能补回历史某一天的手段：日常那条盘中刷新走的是实时快照端点，那个端点没有日期参数，永远回答"此刻"。因此它被排进 crontab，但**每周只跑一次**（周日 04:00）—— 单次执行对上游是全量级请求量，频率是硬约束；其余场合一律不得由 Web API 或其他管理命令间接调用，需要临时补数请人工执行。

> 取消每日逐只历史同步之后，"复牌当天涨跌幅为空"这类快照表达不出来的缺口，会在下一个周日的这次全量校正里被补齐（最多滞后一周）。这是有意的取舍：换掉的是每天一次全量级上游请求。

开盘啦行业记录会存入 `core` 数据库，供 API 和前端展示使用。同一股票属于多个行业时保留多重归属，统计时在每个所属行业中分别计入。

## 6. 日常 crontab

采集调度由下面这一份 crontab 承载：四条采集行（板块资金流、盘中行情、盘后定稿、每周全量校正）与两条参考数据行。把它加进系统所有者的 crontab 即可，用 `crontab -l` 查看当前内容。

```cron
TZ=Asia/Shanghai
APP=/srv/<deploy-dir>
PYTHON=/srv/<deploy-dir>/.venv/bin/python

# 板块资金流：每 5 分钟一轮（时段外的刻度由命令自己的闸门跳掉）
*/5 9-15 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1

# 盘中行情：每 30 分钟刷新当天全市场行情，成功后连锁重建三个派生模块
0,30 9-15 * * 1-5 { cd $APP/backend && $PYTHON manage.py refresh_intraday_quotes && $PYTHON manage.py build_stock_moves && $PYTHON manage.py build_sector_momentum && $PYTHON manage.py build_hundred_day; } >> $APP/backend/logs/daily-prices.log 2>&1

# 盘后定稿：15:35 取已结算的收盘快照（北交所盘后固定价格交易到 15:30），成功后重建
35 15 * * 1-5 { cd $APP/backend && $PYTHON manage.py refresh_intraday_quotes --latest && $PYTHON manage.py build_stock_moves && $PYTHON manage.py build_sector_momentum && $PYTHON manage.py build_hundred_day; } >> $APP/backend/logs/daily-prices.log 2>&1

# 每周日 04:00 的全量校正：重跑最近一年逐只历史行情，补齐历史缺口与复牌股昨收，成功后重建
0 4 * * 7 { cd $APP/backend && $PYTHON manage.py init_stock_daily_prices --years 1 && $PYTHON manage.py build_stock_moves && $PYTHON manage.py build_sector_momentum && $PYTHON manage.py build_hundred_day; } >> $APP/backend/logs/daily-prices.log 2>&1

# 参考数据：与当天行情无关，只需在 15:35 的重建之前就位（行业映射是三个 build_* 的输入）
10 15 * * 1-5 cd $APP/backend && $PYTHON manage.py sync_stock_master >> $APP/backend/logs/stock-master.log 2>&1
15 15 * * 1-5 cd $APP/backend && $PYTHON manage.py sync_kaipanla_industry_snapshot >> $APP/backend/logs/industry.log 2>&1
```

**写入 crontab 必须由系统所有者在自己的登录会话中执行**：macOS 上 `/usr/bin/crontab` 受 TCC 保护，通过自动化工具调起的 shell 读写都会被拒（`Operation not permitted`），这不是配置问题。

几条共同的前提：

- `TZ=Asia/Shanghai` 要声明 —— cron 继承系统时区，部署在别的时区时日期会算到另一个交易日；crontab 里百分号一律写成 `\%`（例如 `date +\%F`），未转义的 `%` 会被当成「换行 + 标准输入」，命令拿到的日期是空的。
- **解释器必须写绝对路径。** cron 的 `PATH` 很窄，裸 `python` 很可能命中没装依赖的系统解释器，表现为 `ModuleNotFoundError: No module named 'django'`。
- **每条任务都必须写成一行。** crontab 里一行就是一条任务，反斜杠续行虽然被支持但极易出错。
- **每一行都以 `>> <log> 2>&1` 收尾，且重定向写在 `{ …; }` 组外面。** 独立的 cron 行之间不传播成功/失败状态：某一行失败既不影响其他行，也不会有人告诉你 —— 「上次跑成功了吗」只能去 `backend/logs/` 翻（库里没有任何运行记录）。只把重定向挂在最后一条命令后面的话，前面几条的输出会跑到 cron 的默认邮件里去。
- **取数与重建用 `&&` 串联**，行情刷新失败时不会拿旧输入白算一遍，也就不会出现 `No daily prices are stored for ...` 那种噪音日志。`&&` 补不出「跳过 ≠ 成功」这层判断：`refresh_intraday_quotes` 落在时段外时打印 `skipped:` 并以退出码 0 结束，后面的 `build_*` 会照常运行 —— 那只是本地重算（毫秒级、幂等），代价可以接受。
- **没有任何一条需要自己生成日期。** `refresh_intraday_quotes` 没有日期参数（快照端点只认「此刻」），三个 `build_*` 默认取库里最新有公共行情的那天 —— 与页面读的锚点是同一个，所以周日的 `init` 会自动落在上一个交易日而不是周日。
- **同一数据集不要并发启动**：有锁保护，第二个进程会直接退出（见 `docs/ops/manage-commands.md` §3.4）。某个业务模块失败不能阻断其他独立模块；开盘啦资金流与盘后日行情/分析是不同数据集，可以独立调度、独立失败。
- **时段外运行不算失败**：命令打印一行 `skipped` 并以退出码 0 结束，所以表达式写得比时段宽是安全的，也不会产生 cron 失败邮件。
- **只启用部分业务模块时，把对应模块的 `build_*` 从链里删掉**：未启用的模块不注册命令，留着会让整条 `&&` 链断在那里（`ENABLED_MODULES` 见 §2）。
- **不要新增任何「从上游同步交易日历」的任务**：交易日由 `chinese-calendar` 本地推导（`core/services/calendar.py`），需要交易日一律调那几个函数。

采集命令**不会**删除旧数据、主动失效缓存或发送外部通知；一个命令失败不中断其他行。「上次跑成功了吗」只能去日志里翻：库里没有运行记录，「更新于 HH:MM」那个时刻是**数据写入时间**，不是运行记录。

### 6.1 时刻表为什么是这几个点

| 时刻 | 动作 | 为什么是这个点 |
| --- | --- | --- |
| 每 5 分钟（`*/5 9-15`） | `fetch_kaipanla_sector_fund_flow`：抓一次板块资金流快照 | 有效刻度 50 个，与 `kaipanla/services/intraday.py` 的 `SNAPSHOT_INTERVAL_MINUTES=5` 对齐。09:00–09:25、午休、15:05 之后共 34 个刻度被时段闸门跳掉 |
| 每 30 分钟（`0,30 9-15`） | `refresh_intraday_quotes`：刷新当天日行情 → 重建三个派生模块 | 有效刻度 10 个（09:30–11:30 / 13:00–15:00），最后一个就是 15:00 —— 收盘那一刻的快照，它已在时段内、不需要 `--latest`。页面在收盘前就能跟随当天；一次刷新约 6 个上游请求（全市场分页），这个节拍才付得起 |
| 15:35 | `refresh_intraday_quotes --latest` → 重建 | **不要提前到 15:00–15:05**：北交所盘后固定价格交易到 15:30，早于它拿到的不是结算终值 |
| 15:10 / 15:15 | 参考数据 | 与当天行情无关，只需在 15:35 的重建之前就位 —— 行业映射是三个 `build_*` 的输入 |
| 周日 04:00 | `init_stock_daily_prices --years 1` → 重建 | 逐只历史接口是全量级请求，放在没有交易、上游最空闲的时段。它补的是快照表达不出来的东西 |

**为什么表达式不写细时段。** 判定交易日与交易时段的能力已经完整地落在命令里（`is_trading_day` + `is_trading_session`），crontab 只需要「周一到周五的交易钟点」这个粗范围即可，不必再复刻午休与收盘的边界。多出来的刻度会空跑一次、打印一行 `skipped` 并以退出码 0 结束 —— 不打上游、不写库、不产生失败告警。换掉的是一个会随交易时段调整而**悄悄失准的第二定义**：把 `9-11,13-14` 这种窗口抄进 crontab，日后改 `core/services/calendar.py` 的 `TRADING_SESSIONS` 就得记得同步改 crontab，忘了就是丢刻度。

个股日行情**只有一条日常写入路径**（`refresh_intraday_quotes`），所以不存在「两条口径互相覆盖」的问题；`init` 是校正，不是第二条日常链路。

开盘啦可被上游临时屏蔽。发生 403、429、超时、限流或无数据时，命令应以非零退出并记录失败状态，但不会删除旧快照、不会主动失效缓存、不会影响其他定时任务，也不会发送外部通知。没有旧数据时，该模块 API 返回 `202 DATA_PREPARING` 或本地无数据状态；前端可以没有内容。

### 6.2 跳过、失败与恢复

**「跳过」和「失败」要分开**：落在交易时段外（含周末、节假日）时命令**不算失败** —— 它不访问上游、不写库、不记失败状态，打印一行 `skipped: …` 后以**退出码 0** 结束，因此日志里会看到 `action=skipped reason=outside_trading_session` 或 `reason=not_a_trading_day`，但不会有 `FAILED`。只有上游/写入故障才走非零退出。

跳过有两种原因，语义不同：`refresh_intraday_quotes` 与 `fetch_kaipanla_sector_fund_flow` 在时段外都跳过（加 `--latest` 可绕过）；但**非交易日连 `--latest` 也会跳过日行情刷新** —— 快照端点没有日期参数，休市日跑它只能拿到上一交易日的收盘态，写下去等于把那份数据冒充成当天。资金流的 `--latest` 允许在非交易日强制采集，因为它采的是「最近一个交易日的收盘快照」这个明确概念，这一点两者刻意不同。

**这份 crontab 不重试。** 上游按实时负载动态限流，失败以限流为主，所以补跑要克制：

- 盘中的行情刷新失败：不用管，下一个 30 分钟刻度自己会来。
- 盘后定稿失败：当天数据停在盘中最后一版快照（页面仍能读到数据，只是不是定稿）。用 `refresh_intraday_quotes --latest` 手动跑**一次**即可 —— 别连续重试，越试越差。
- 周日校正失败：下一个周日自己会来；确有需要时手动重跑一次 `init_stock_daily_prices --years 1`（与上游一致时不写任何行，重跑是安全的）。
- 需要更强强度时，把那两行改写成内联退避循环：`for i in 1 2 3; do <原命令链> && exit 0; sleep 600; done; exit 1`。

排查的第一现场是 `backend/logs/` 下的四个文件：`kaipanla.log`、`daily-prices.log`、`stock-master.log`、`industry.log`。各命令的完整参数、失败语义与排查见 `docs/ops/manage-commands.md` §10。

## 7. 生产进程管理、静态文件与 HTTPS

生产环境**不使用** `python manage.py runserver`（开发服务器，无进程守护、不适用生产），也不使用 Vite 开发服务器。下面的顺序是"能上线"的最小集。

### 7.1 安装 WSGI 服务器

WSGI 服务器不在 `requirements.txt` 里（本地开发用不着），生产环境单独装：

```bash
pip install gunicorn
```

若希望和其余依赖一起锁定版本，可把它追加进 `backend/requirements.txt` 再一同安装；无论哪种方式，`manage.py` 系列命令仍照常可直接执行。

### 7.2 以 WSGI 服务常驻

```bash
cd /srv/<deploy-dir>/backend
/srv/<deploy-dir>/.venv/bin/gunicorn backend.wsgi:application \
  --bind 127.0.0.1:8000 \
  --workers 2 \
  --timeout 60
```

- `backend.wsgi:application` 是 `backend/backend/wsgi.py` 的入口模块，不要改成项目外路径。
- 绑 `127.0.0.1` 而非 `0.0.0.0`：对外只经反向代理，Django 不直接暴露在公网。
- `--workers 2` 足够。本项目是单机 SQLite 部署，worker 越多写锁竞争越明显；真正耗时的工作都在 crontab 跑的管理命令里，不在 Web 进程里。
- `--timeout` 必须**大于**三个盘后模块读路径「本地按需生成派生结果」的耗时（通常几秒），否则一次生成会被 worker 超时杀掉。

用 systemd 常驻（示例；路径按实际替换）：

```ini
# /etc/systemd/system/market-review.service
[Unit]
Description=A-share market review (Django + gunicorn)
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/srv/<deploy-dir>/backend
ExecStart=/srv/<deploy-dir>/.venv/bin/gunicorn backend.wsgi:application \
    --bind 127.0.0.1:8000 --workers 2 --timeout 60
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now market-review.service
systemctl status market-review.service
```

不用 systemd 时，supervisor 等等价工具都可以；关键只有三点：**常驻、崩溃重启、能被 reload**。

**不需要**给 systemd 配 `EnvironmentFile`：`backend/backend/env.py` 自己读取仓库根目录的 `.env`。配置生效时机分两类：

- 启动时一次性读取的（`DJANGO_SECRET_KEY`、`DJANGO_DEBUG`、`DJANGO_ALLOWED_HOSTS`、`ENABLED_MODULES`、五个数据库路径等 settings 项）→ **改完必须重启服务**；
- 运行期按需读取的（上游凭据、超时、各类开关）→ 进程内缓存最多 5 秒，**改完不重启也会生效**；crontab 里的管理命令每次都是新进程，一律立即生效。

### 7.3 反向代理与静态文件

- 反向代理通过 HTTPS 提供 `frontend/dist/`，并把 `/api/`、`/admin/` 代理给 `127.0.0.1:8000`。当前版本按同源部署：仅接受配置在 `DJANGO_ALLOWED_HOSTS` 和 `CSRF_TRUSTED_ORIGINS` 中的域名，不启用跨域 CORS。
- **SPA 路由必须回退**：除 `/api/`、`/admin/`、`/static/` 之外的路径一律返回 `frontend/dist/index.html`，否则用户刷新非根路径会 404。
- Django 管理后台依赖静态文件，而 `backend/settings.py` **目前没有设置 `STATIC_ROOT`**（Django 默认值为 `None`）。因此直接跑 `collectstatic` 会失败，部署前**必须二选一**：
  1. 给 settings 补 `STATIC_ROOT`（建议从 `.env` 读取，和其余路径同一口径），执行 `python manage.py collectstatic --noinput`，再由反向代理把该目录映射到 `/static/`；
  2. 或退而求其次，让反向代理直接把虚拟环境内 `django/contrib/admin/static/` 下的 `admin/` 映射到 `/static/admin/`（可行但依赖安装路径，升级 Django 后要复查）。
  不能假设开发服务器的静态文件行为适用于生产。
- 不在 HTTP 环境中把 `SESSION_COOKIE_SECURE` 或 `CSRF_COOKIE_SECURE` 改为 `false`。本地纯 HTTP 调试如必须临时改动，仅限本地 `.env`，不得进入生产 `.env.example` 或源码。

#### 7.3.1 Nginx 配置示例

本仓库**唯一**的完整反向代理配置在这里，其他文档只写链接。下面这份覆盖 HTTP→HTTPS 跳转、证书与安全响应头、`/assets/` 长缓存、`/static/`、`/api/`、`/admin/` 与 SPA 回退。

```nginx
# /etc/nginx/conf.d/market-review.conf

# 1) HTTP 全量跳 HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name review.example.com;

    # 证书续期质询等例外路径可按需在此放行；其余一律跳转
    location /.well-known/acme-challenge/ {
        root /var/www/acme;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}

# 2) HTTPS 主站：静态站点 + /api/ /admin/ 反代
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;   # nginx ≥ 1.25.1 的写法；更早版本改为 `listen 443 ssl http2;`
    server_name review.example.com;

    ssl_certificate     /etc/letsencrypt/live/review.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/review.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    # 与 DJANGO_ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS 保持同一个域名
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options    "nosniff" always;
    add_header X-Frame-Options           "DENY" always;
    add_header Referrer-Policy           "strict-origin-when-cross-origin" always;

    charset utf-8;
    client_max_body_size 2m;

    # 3) 前端构建产物
    root /srv/<deploy-dir>/frontend/dist;
    index index.html;

    # Vite 产物带内容哈希，可长缓存。
    # 注意：location 里一旦出现 add_header，就会**丢掉** server 级继承来的全部
    # add_header。若要保留上面的安全响应头，这里应把安全头一并重复，
    # 或改用 include 一个公共 snippet。
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    # 4) Django 管理后台静态文件
    #    注意：settings.py 目前没有 STATIC_ROOT。部署前必须二选一：
    #    a) 补上 STATIC_ROOT 并执行 collectstatic --noinput，然后把 alias 指过去；
    #    b) 或临时 alias 到虚拟环境内的 admin 静态目录（升级 Django 后需复查）。
    location /static/ {
        alias /srv/<deploy-dir>/backend/staticfiles/;
        expires 30d;
        access_log off;
    }

    # 5) API 反代
    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;   # 生产必须，否则 Django 认为是 HTTP
        # 读路径可能触发一次本地按需生成（几秒），超时要给足
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }

    # 6) 管理后台
    location /admin/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # 7) SPA 路由回退：除上面几条外的路径都交给 index.html
    #    少了这一条，用户刷新 /stock-moves 会 404
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

上线后依次执行 `nginx -t`、`systemctl reload nginx`，再用 `https://域名/api/core/health/` 验证反向代理链路。登录时依次验证 `session/` 与 `login/`，确认 cookie 正常下发（`Secure` + `SameSite`）。

## 8. 备份、清理、故障恢复与回滚

- 本期**没有**自动备份、自动归档、自动清理或外部通知。SQLite、文件缓存和日志的备份与保留由系统所有者手动负责。
- 建议在升级或迁移前，停止对应 crontab 行后，手动复制 `backend/data/`、`backend/cache/`、`.env`（安全位置）和反向代理配置；恢复时停止服务与 crontab、还原这些文件、重新运行 `python manage.py check` 后再启动。
- 单一业务模块采集失败：不删除该模块 SQLite 或缓存；翻该模块的命令日志（事件名 `data_command_failed`，库里没有运行状态可查），修正 `.env`/网络/上游问题后在适当时间手动重跑该模块命令。
- 模块代码回滚：回滚代码与相应迁移前先停止该模块 crontab；若迁移不可逆，以部署前手动备份的对应 SQLite 文件恢复。`core` 与其余模块仍可独立运行。
- 不要删除 `core`；可以通过 `ENABLED_MODULES` 关闭任何一个业务模块。关闭后该模块 URL 不挂载，其他模块继续运行。

## 9. 发布前验证

不访问真实上游时可运行：

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
cd ..
./scripts/check_module_matrix.sh
cd frontend
npm test -- --run
npm run lint
npm run build
```

真实网页/API 验收必须在系统所有者提供现成服务地址、测试账号并明确允许后执行；不得为了验收自行启动服务或向真实上游发起试采集。待执行项目见验收追踪文档。
