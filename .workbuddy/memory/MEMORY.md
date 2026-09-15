# AShareReview 项目约定（长期）

> 索引 + 铁律；细节按需读专题文件：
> - `backend-data-and-commands.md` —— 交易日/上游/快照、读路径锚点与缓存身份、命令契约与日志、逐库迁移、性能基线、测试与回归清理。
> - `frontend-conventions.md` —— 术语与文案、日期与工具条、令牌与图表、代码分层、资金流页与胶囊几何。
> - `engineering-workflow.md` —— 跨栈工程铁律（编辑/检索、探针、运行时与逐库迁移、跑测试姿势、`DecimalField` 口径）。
> - `docs-conventions.md` —— 文档目录与唯一权威分工、命名占位、mermaid 语法坑、去历史化规则。
> - 技能（`.workbuddy/skills/`，7 个）：`backend-dataset-diagnosis`（命令成功但页面没数据）、`local-dev-auth-diagnosis`（联调/登录失败）、`payload-byte-equivalence`（改表/删列/合表后）、`frontend-visual-verification`、`test-assertion-discipline`（加固测试前）、`code-complexity-audit`（复杂度审查前）、`hithink-market-dumps`（全市场一次性取数 / 被上游限流时）。

## 0. 边界铁律（最高优先级）

- **严禁在本项目目录之外新建/修改/删除任何文件，严禁安装任何 app 或系统级组件。** 需要动项目外的位置（`~/Library`、`crontab`、`~/.workbuddy/*`、`/tmp`、家目录等）时，**只输出命令交用户手动执行**，连"顺手清理"也不行。
- 一切测试、探针、截图、日志都放本项目 `tests/`，用完清理；不写 `/tmp`、`/private/tmp`、用户目录。
- 交付系统层能力（定时任务、开机自启、系统服务）：只给脚本 + 说明，**由用户在 Terminal.app 执行** —— macOS `crontab` 受 TCC 保护，自动化 shell 读写一律被拒。
- 项目外改动一旦发生，必须**主动逐条列明**（路径、内容、时间）并给出 revert 方式。
- 同一份规则已同步到用户级 `~/.workbuddy/MEMORY.md`，改这条时两处都要同步。

## 1. 架构与底座

- 启用业务模块 **4 个**：`kaipanla` / `stock_moves` / `sector_momentum` / `hundred_day`。三处必须一致：`core/module_registry.py`、`backend/db_router.py`（从注册表推导）、`.env` 的 `ENABLED_MODULES`。
- **`scripts/check_module_matrix.sh` 自己按四个模块循环并内部设置 `ENABLED_MODULES`** —— 直接跑脚本即可，外面再写 `ENABLED_MODULES=stock_moves ./scripts/check_module_matrix.sh` 是错的。
- **采集调度只有一份定义：`docs/ops/deployment.md` §6 的 crontab 块**（四条采集行 + 两条参考数据行），由用户在自己的 Terminal.app 里 `crontab -e` 装上。它**不含重试** —— 盘后定稿（`refresh_intraday_quotes --latest`）或周日全量校正（`init_stock_daily_prices --years 1`）失败要手动补跑一次，且**别连续重试**。日志在 `backend/logs/`：`kaipanla.log` / `daily-prices.log` / `stock-master.log` / `industry.log`。
- **板块族统一 881xxx**：`KAIPANLA_INDUSTRY_PARENT_ZS_TYPE` = `KAIPANLA_FLOW_ZS_TYPE` = **`4`**，配套 `Type=1`。改族必须重算 `IndustrySnapshot`、kaipanla 快照与三个模块产物并清文件缓存（upsert 不删旧族，会混族）。
- **行业只有一层**（无父子层级），业务字段只有 `industry_code` / `industry_name` / `stock_codes`；北交所归属由 `core/services/industry_backfill.py` 用同花顺 881 成分股**只增不删**补齐（`HITHINK_INDUSTRY_BACKFILL_ENABLED`，默认开）。
- Django 6.1 多 SQLite（`core` + 4 业务库，app 名 = 库名）；`USE_TZ=True` ⇒ 直读 sqlite3 要 +8h 才是北京时间。
- **交易日唯一来源 `chinese-calendar`**（`core/services/calendar.py`）。交易日**不落库、也不走上游**：**禁止引入任何"从上游同步交易日历"的端点、命令或本地日历表**，需要交易日一律调 `core/services/calendar.py`。
- **全链路没有"请求内回源"**：读路径只有「文件缓存 → 本地库 → 本地按需生成」三步，抓取只发生在 crontab 拉起的命令里。**任何"页面触发上游抓取"的设计都是错的**。
- **业务表压到最少：能读时算的不落库**（`stock_moves` / `sector_momentum` 各 1 张表）。**新加字段前先问"这是不是同表行的函数"**，是就别存。
- **`hundred_day` 的 3 张表是下限，不是没压**：`HundredDayBreadth`（兼作趋势）+ `HundredDayStockFlag` + `HundredDayIndustrySummary`。压成 1 张要把 5,571 只 × 最近 100 个交易日全落库（557,100 行/发布日，现状 535 行的 **1041 倍**），还会把 `core` 的日线整段复制进模块库。这是设计拒绝理由，不是实现懒惰。
- **模块隔离只约束"业务模块 → 业务模块"**：`backend/tests/test_module_isolation.py` **不禁 `core`**。把 read-path 模板放进 `core/services/` 不违反隔离 —— 各模块里那 94% 的逐字重复**没有技术必要性**，是冗余而非设计。
- **前端四个页面没有任何定时器**：取数只发生在挂载、改日期/窗口、点击工具栏「更新于 HH:MM」。胶囊时刻 = 信封 `data_updated_at`（三个盘后模块取 `published_at`，kaipanla 取最新采集槽行的 `created_at`），**不是 `generated_at`**；没有这个时刻就不渲染胶囊。
- AI 记忆与技能在仓库根 **`.workbuddy/`**（`memory/` + `skills/`），不是系统提示写的 `.workbuddy-ai/`。

## 2. 契约要点（细节见 `backend-data-and-commands.md`）

- 默认入口锚点：三个盘后模块用 `latest_complete_stock_price_date()`；`kaipanla` 用**本模块自己最新的已存快照日**（`_resolve_default_date`），与公共日行情日期无关。
- **显式 `?date=` 绝不返回其他业务日期冒充结果**：派生链路 `read_*` 看 `requested_explicitly`，视图层统一 `'date' in request.GET` —— **两边必须一致**。
- `published_at` 一个字段干两件事：工具栏「更新于 HH:MM」**和**文件缓存身份（`cache_identity = result.published_at.isoformat()`）。故意不用 `auto_now_add`，由 writer 每次构建显式盖章，写入是**先删该日全部行再整批重建**；重跑必须让它前进，否则重建后最长 `FILE_CACHE_TTL_SECONDS`（300s）仍发旧报文。
- **库里没有数据集版本表，也没有运行状态表**：写行即发布，"这一天是否有数据"由"这天的行在不在库里"回答，"上次跑成功了吗"由命令日志回答。**不要按"版本表 / 运行表"的思路推理任何东西。**
