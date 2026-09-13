# 部署与运行说明

> 本文适用于本地开发机和阿里云生产机。两者使用同一份代码；环境差异仅放在仓库根目录 `.env`，不修改 Python 或前端源码。本文中的 `/srv/<deploy-dir>` 是生产部署路径示例，需替换为实际绝对路径。

## 1. 首次部署前检查

1. 使用受支持的 Python 环境创建虚拟环境，并在 `backend/` 安装 `requirements.txt` 中的依赖。
   - 其中 `chinese-calendar` 用于判定周末与法定节假日（交易日判定的第一层）。它**按年内置节假日数据**，每年国务院放假安排公布后需升级该包并重启服务；跨年未升级时该层判定会自动退回同花顺交易日历，不会中断采集。
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
| 缓存与锁 | `FILE_CACHE_*`、`LOCK_DIRECTORY`、`REMOTE_REPAIR_ENABLED`、`REMOTE_REPAIR_HARD_TIMEOUT_SECONDS` | `REMOTE_REPAIR_ENABLED` 是开/关；开启时一次远程同步修复只发一次有界抓取（单页、不重试），只有这两个旋钮：`REMOTE_REPAIR_HARD_TIMEOUT_SECONDS` 是真正的耗时上限（默认 5 秒，会收窄 `KAIPANLA_TIMEOUT_SECONDS`），`REMOTE_REPAIR_RETRY_AFTER_SECONDS` 只是 202/503 响应体里的重试提示值、不影响抓取时长。仅板块资金流走这条路径；不要将全市场初始化放进 Web 请求。三个盘后模块的按需生成只读本地数据，不受这些约束。 |
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

管理员通过 `/admin/` 查看公共数据版本、模块运行状态及各模块数据；后台只查看状态，不提供在线启动、停止或重跑采集命令。

## 5. 首次数据准备

在全新数据库中，按顺序执行：

```bash
python manage.py sync_trading_calendar
python manage.py sync_stock_master
python manage.py sync_kaipanla_industry_snapshot
python manage.py init_stock_daily_prices --years 1
```

前三条各自幂等，重复执行只做增量同步。

`init_stock_daily_prices --years 1` 第一次执行会导入「以执行日为终点的最近一年」公共前复权日行情。**它不是一次性命令，之后可以也应该手动重跑**：第二次起会先逐条与上游比对，只写入有差异的行，是**按上游校正与补齐历史行情的官方手段**（`--dry-run` 会先报告将改动多少行；全部一致时输出 `no changes`）。不要因为"首次准备"这个标题而不敢重跑，也不要把它交给 Web API、定时任务或其他管理命令间接调用 —— 单次执行对上游是全量级请求量，必须由人显式触发。

开盘啦行业记录会存入 `core` 数据库，供 API 和前端展示使用。同一股票属于多个行业时保留多重归属，统计时在每个所属行业中分别计入。

## 6. 日常 crontab（四个逻辑组）

先在 `crontab -e` 顶部声明时区和绝对路径。百分号在 crontab 中必须写成 `\%`。下面示例将标准输出和错误输出分开追加到 `backend/logs/`；一个命令失败不会中断其他行。

```cron
TZ=Asia/Shanghai
APP=/srv/<deploy-dir>
PYTHON=/srv/<deploy-dir>/.venv/bin/python

# 1) 公共参考数据：交易日、股票主数据、开盘啦行业及股票关系。
5 15 * * 1-5 cd $APP/backend && $PYTHON manage.py sync_trading_calendar >> $APP/backend/logs/calendar.log 2>&1
10 15 * * 1-5 cd $APP/backend && $PYTHON manage.py sync_stock_master >> $APP/backend/logs/stock-master.log 2>&1
15 15 * * 1-5 cd $APP/backend && $PYTHON manage.py sync_kaipanla_industry_snapshot >> $APP/backend/logs/industry.log 2>&1

# 2) 开盘啦板块资金流：仅交易时段；收盘快照单独在 15:00 获取。
30-59/5 9 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1
*/5 10 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1
0-30/5 11 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1
*/5 13-14 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1
0 15 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1
# 可选：盘后再刷一次收盘快照（含结算后的修正值）。落库时刻仍是 15:00 槽，覆盖而非新增。
# 5 16 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow --latest >> $APP/backend/logs/kaipanla.log 2>&1

# 3) 公共个股日行情：只同步当天，日期由上海时区产生。
20 15 * * 1-5 cd $APP/backend && $PYTHON manage.py sync_stock_daily_prices --date "$(date +\%F)" >> $APP/backend/logs/daily-prices.log 2>&1

# 4) 三个盘后分析：只读本地公共数据，互相独立。
35 15 * * 1-5 cd $APP/backend && $PYTHON manage.py build_stock_moves --date "$(date +\%F)" >> $APP/backend/logs/stock-moves.log 2>&1
40 15 * * 1-5 cd $APP/backend && $PYTHON manage.py build_sector_momentum --date "$(date +\%F)" >> $APP/backend/logs/sector-momentum.log 2>&1
45 15 * * 1-5 cd $APP/backend && $PYTHON manage.py build_hundred_day --date "$(date +\%F)" >> $APP/backend/logs/hundred-day.log 2>&1
```

开盘啦可被上游临时屏蔽。发生 403、429、超时、限流或无数据时，命令应以非零退出并记录失败状态，但不会删除旧快照、不会主动失效缓存、不会影响其他定时任务，也不会发送外部通知。没有旧数据时，该模块 API 返回 `202 DATA_PREPARING` 或本地无数据状态；前端可以没有内容。

### 6.1 盘中链路（可选）

§6 的四组是**盘后管线**，只在收盘后发布当天的权威版本。若希望页面在收盘前就能跟随当天数据，仓库另提供一套盘中编排脚本，把「交易日历同步 + 5 分钟板块资金流 + 30 分钟全市场行情（并重建三个盘后模块）」包成三个子命令：

```bash
scripts/intraday_orchestrator.sh calendar   # 开盘前同步交易日历
scripts/intraday_orchestrator.sh fundflow   # 抓一次板块资金流快照
scripts/intraday_orchestrator.sh quotes     # 刷新当天全市场行情并重建三个模块
```

安装为定时任务：

- **macOS**：`scripts/install_intraday_launchd.sh install`（推荐）。macOS 的 `crontab` 受 TCC 保护，非交互 shell 写入会报 `Operation not permitted`；用户级 launchd 代理不需要额外授权。
- **Linux / 通用**：`scripts/install_intraday_cron.sh`。

脚本自己只做时间粗筛（时段外直接以 0 退出，不写噪声日志、也不触发 cron 失败邮件），真正的交易日判定由 Django 命令完成。盘中链路与盘后管线**共用同一套数据集与字段语义**（当天行情统一由 `refresh_intraday_quotes` 用实时快照刷新，收盘后以 `sync_stock_daily_prices` 的历史接口为权威覆盖），因此两组互相覆盖而不产生歧义，重复安装只会让采集更密。

**安装 crontab / launchd 必须由系统所有者在自己的登录会话中执行**；通过自动化工具调起的 shell 会被 macOS 直接拒绝，这不是脚本缺陷。

脚本内部命令的完整参数、失败语义与排查见 `docs/ops/manage-commands.md` §9.2 与 §10。

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
- 一份完整可用的 Nginx 配置示例（HTTP→HTTPS 跳转、证书与安全响应头、`/assets/` 长缓存、`/static/`、`/api/`、`/admin/`、SPA 回退）见仓库根 `README.md` 的「生产环境运维 → Nginx 配置示例」。本节只列易错点，不重复整份配置。
- Django 管理后台依赖静态文件，而 `backend/settings.py` **目前没有设置 `STATIC_ROOT`**（Django 默认值为 `None`）。因此上面直接跑 `collectstatic` 会失败，部署前**必须二选一**：
  1. 给 settings 补 `STATIC_ROOT`（建议从 `.env` 读取，和其余路径同一口径），执行 `python manage.py collectstatic --noinput`，再由反向代理把该目录映射到 `/static/`；
  2. 或退而求其次，让反向代理直接把虚拟环境内 `django/contrib/admin/static/` 下的 `admin/` 映射到 `/static/admin/`（可行但依赖安装路径，升级 Django 后要复查）。
  不能假设开发服务器的静态文件行为适用于生产。
- 不在 HTTP 环境中把 `SESSION_COOKIE_SECURE` 或 `CSRF_COOKIE_SECURE` 改为 `false`。本地纯 HTTP 调试如必须临时改动，仅限本地 `.env`，不得进入生产 `.env.example` 或源码。

## 8. 备份、清理、故障恢复与回滚

- 本期**没有**自动备份、自动归档、自动清理或外部通知。SQLite、文件缓存和日志的备份与保留由系统所有者手动负责。
- 建议在升级或迁移前，停止对应 crontab 行后，手动复制 `backend/data/`、`backend/cache/`、`.env`（安全位置）和反向代理配置；恢复时停止服务与 crontab、还原这些文件、重新运行 `python manage.py check` 后再启动。
- 单一业务模块采集失败：不删除该模块 SQLite 或缓存；查看 Django admin 的 `ModuleRunStatus` 和模块日志，修正 `.env`/网络/上游问题后在适当时间手动重跑该模块命令。
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
