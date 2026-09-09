# 部署与运行说明

> 本文适用于本地开发机和阿里云生产机。两者使用同一份代码；环境差异仅放在仓库根目录 `.env`，不修改 Python 或前端源码。本文中的 `/srv/a-share-market-review` 是生产部署路径示例，需替换为实际绝对路径。

## 1. 首次部署前检查

1. 使用受支持的 Python 环境创建虚拟环境，并在 `backend/` 安装 `requirements.txt` 中的依赖。
2. 在 `frontend/` 安装锁定版本的依赖并运行 `npm run build`，生成 `frontend/dist/`。
3. 复制 `.env.example` 为根目录 `.env`；该文件不能提交到 Git，文件权限应仅允许部署账户读取（例如 `chmod 600 .env`）。
4. 创建并确保部署账户可写：

   ```bash
   mkdir -p backend/data backend/data/locks backend/cache backend/logs
   ```

   `backend/data/` 内保存六个 SQLite 文件，`backend/cache/` 保存文件缓存，锁目录为 `backend/data/locks/`。这些均为运行时数据，不提交到版本库。
5. 确认服务器时区为 `Asia/Shanghai`；同时将 `.env` 的 `DJANGO_TIME_ZONE=Asia/Shanghai` 保持不变。

## 2. `.env` 配置清单

以 `.env.example` 为唯一字段清单。生产环境至少需要检查以下分组：

| 分组 | 必填/关键字段 | 说明 |
| --- | --- | --- |
| Django | `DJANGO_SECRET_KEY`、`DJANGO_DEBUG=false`、`DJANGO_ALLOWED_HOSTS`、`DJANGO_TIME_ZONE` | 密钥使用随机长值；生产域名必须填写，不能使用 `*`。 |
| SQLite | 六个 `*_DATABASE_PATH` | 默认均放在 `backend/data/`，可改为可写的绝对路径。 |
| 缓存与锁 | `FILE_CACHE_*`、`LOCK_DIRECTORY`、`REMOTE_REPAIR_*` | 修复路径最多一次远程尝试、硬超时默认不超过 5 秒；不要将全市场初始化放进 Web 请求。 |
| 模块开关 | `ENABLED_MODULES` | 逗号分隔的静态模块列表；可独立关闭一个业务模块。 |
| 同花顺 REST | `HITHINK_FINANCE_*` | 只用于股票表、交易日和前复权日线；`HITHINK_FINANCE_API_KEY` 仅放在 `.env`。 |
| 开盘啦 | `KAIPANLA_*`、`KPL_*` | 用于板块资金流和父行业→子行业→股票关系；凭据不能出现在日志或版本库。 |
| 东方财富 | `EASTMONEY_*` | 用于东方财富板块资金流；403、429、超时和屏蔽允许失败。 |
| 浏览器安全 | `SESSION_COOKIE_*`、`CSRF_COOKIE_*`、`CSRF_TRUSTED_ORIGINS` | 生产 HTTPS 下保持 secure cookie 为 `true`，可信来源填写实际 `https://` 域名。当前版本按同源部署，不启用跨域 CORS。 |

生产示例只表达结构，不包含真实值：

```dotenv
DJANGO_SECRET_KEY=replace-with-a-unique-random-production-secret
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=review.example.com
DJANGO_TIME_ZONE=Asia/Shanghai
CSRF_TRUSTED_ORIGINS=https://review.example.com
CORS_ALLOWED_ORIGINS=https://review.example.com
SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
```

## 3. 初始化六个 SQLite 数据库

所有命令从 `backend/` 目录执行。路由器只允许 `core` 写入 `default`，每个业务 App 写入同名数据库。按下面顺序执行一次迁移；可安全重复执行。

```bash
python manage.py migrate --database=default
python manage.py migrate --database=kaipanla
python manage.py migrate --database=eastmoney
python manage.py migrate --database=stock_moves
python manage.py migrate --database=sector_momentum
python manage.py migrate --database=hundred_day

python manage.py check
python manage.py createsuperuser
```

管理员通过 `/admin/` 查看公共数据版本、模块运行状态及各模块数据；后台只查看状态，不提供在线启动、停止或重跑采集命令。

## 4. 首次数据准备（只运行一次）

在全新数据库中，按顺序执行：

```bash
python manage.py sync_trading_calendar
python manage.py sync_stock_master
python manage.py sync_kaipanla_industry_snapshot
python manage.py init_stock_daily_prices --years 1
```

`init_stock_daily_prices --years 1` 的前置条件是 `DailyPrice` 为空。它只获取“以执行日为终点的最近一年”公共前复权日行情；成功后不应再次执行，也不得由 Web API、定时任务或其他管理命令间接调用。

开盘啦子行业记录会存入 `core` 数据库，但当前 API 和前端只使用、展示父行业。父行业的股票列表由其子行业股票去重汇总；同一股票属于多个父行业时保留多重归属。

## 5. 日常 crontab（五个逻辑组）

先在 `crontab -e` 顶部声明时区和绝对路径。百分号在 crontab 中必须写成 `\%`。下面示例将标准输出和错误输出分开追加到 `backend/logs/`；一个命令失败不会中断其他行。

```cron
TZ=Asia/Shanghai
APP=/srv/a-share-market-review
PYTHON=/srv/a-share-market-review/.venv/bin/python

# 1) 公共参考数据：交易日、股票主数据、开盘啦父/子行业及股票关系。
5 15 * * 1-5 cd $APP/backend && $PYTHON manage.py sync_trading_calendar >> $APP/backend/logs/calendar.log 2>&1
10 15 * * 1-5 cd $APP/backend && $PYTHON manage.py sync_stock_master >> $APP/backend/logs/stock-master.log 2>&1
15 15 * * 1-5 cd $APP/backend && $PYTHON manage.py sync_kaipanla_industry_snapshot >> $APP/backend/logs/industry.log 2>&1

# 2) 开盘啦板块资金流：仅交易时段；收盘快照单独在 15:00 获取。
30-59/5 9 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1
*/5 10 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1
0-30/5 11 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1
*/5 13-14 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1
0 15 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_kaipanla_sector_fund_flow >> $APP/backend/logs/kaipanla.log 2>&1

# 3) 东方财富板块资金流：使用与开盘啦相同的交易时段表达式和独立日志。
30-59/5 9 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_eastmoney_sector_fund_flow >> $APP/backend/logs/eastmoney.log 2>&1
*/5 10 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_eastmoney_sector_fund_flow >> $APP/backend/logs/eastmoney.log 2>&1
0-30/5 11 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_eastmoney_sector_fund_flow >> $APP/backend/logs/eastmoney.log 2>&1
*/5 13-14 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_eastmoney_sector_fund_flow >> $APP/backend/logs/eastmoney.log 2>&1
0 15 * * 1-5 cd $APP/backend && $PYTHON manage.py fetch_eastmoney_sector_fund_flow >> $APP/backend/logs/eastmoney.log 2>&1

# 4) 公共个股日行情：只同步当天，日期由上海时区产生。
20 15 * * 1-5 cd $APP/backend && $PYTHON manage.py sync_stock_daily_prices --date "$(date +\%F)" >> $APP/backend/logs/daily-prices.log 2>&1

# 5) 三个盘后分析：只读本地公共数据，互相独立。
35 15 * * 1-5 cd $APP/backend && $PYTHON manage.py build_stock_moves --date "$(date +\%F)" >> $APP/backend/logs/stock-moves.log 2>&1
40 15 * * 1-5 cd $APP/backend && $PYTHON manage.py build_sector_momentum --date "$(date +\%F)" >> $APP/backend/logs/sector-momentum.log 2>&1
45 15 * * 1-5 cd $APP/backend && $PYTHON manage.py build_hundred_day --date "$(date +\%F)" >> $APP/backend/logs/hundred-day.log 2>&1
```

东方财富可被上游临时屏蔽。发生 403、429、超时、限流或无数据时，命令应以非零退出并记录失败状态，但不会删除旧快照、不会主动失效缓存、不会影响开盘啦或其他定时任务，也不会发送外部通知。没有旧数据时，该模块 API 返回 `202 DATA_PREPARING` 或本地无数据状态；前端可以没有内容。

## 6. 前端静态文件与 HTTPS

- 反向代理应通过 HTTPS 提供 `frontend/dist/`，并将 `/api/`、`/admin/` 代理给 Django。当前版本按同源部署：仅接受配置在 `DJANGO_ALLOWED_HOSTS` 和 `CSRF_TRUSTED_ORIGINS` 中的域名，不应依赖 `CORS_ALLOWED_ORIGINS` 实现跨域访问。
- Django 管理后台依赖静态文件。生产反向代理需要把 Django 收集后的静态目录映射到 `/static/`；在启用服务前，确认当前部署配置已经提供可写的 Django `STATIC_ROOT` 并成功执行 `python manage.py collectstatic`。若未配置该目录，先补齐部署配置，不能假设开发服务器的静态文件行为适用于生产。
- 不在 HTTP 环境中把 `SESSION_COOKIE_SECURE` 或 `CSRF_COOKIE_SECURE` 改为 `false`。本地纯 HTTP 调试如必须临时改动，仅限本地 `.env`，不得进入生产 `.env.example` 或源码。

## 7. 备份、清理、故障恢复与回滚

- 本期**没有**自动备份、自动归档、自动清理或外部通知。SQLite、文件缓存和日志的备份与保留由系统所有者手动负责。
- 建议在升级或迁移前，停止对应 crontab 行后，手动复制 `backend/data/`、`backend/cache/`、`.env`（安全位置）和反向代理配置；恢复时停止服务与 crontab、还原这些文件、重新运行 `python manage.py check` 后再启动。
- 单一业务模块采集失败：不删除该模块 SQLite 或缓存；查看 Django admin 的 `ModuleRunStatus` 和模块日志，修正 `.env`/网络/上游问题后在适当时间手动重跑该模块命令。
- 模块代码回滚：回滚代码与相应迁移前先停止该模块 crontab；若迁移不可逆，以部署前手动备份的对应 SQLite 文件恢复。`core` 与其余模块仍可独立运行。
- 不要删除 `core`；可以通过 `ENABLED_MODULES` 关闭任何一个业务模块。关闭后该模块 URL 不挂载，其他模块继续运行。

## 8. 发布前验证

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
