# a_share_market_review 项目约定（长期）

> 专题文件（按需读取）：
> - `.workbuddy/memory/frontend-conventions.md` —— 术语/页面文案、日期与工具条、设计令牌与图表、板块资金流页结构。**改前端任何文案、样式、图表前先读它。**
> - `.workbuddy/memory/backend-data-and-commands.md` —— 交易日/上游/快照、命令契约与日志、性能基线、测试与回归清理。
> - `.workbuddy/skills/backend-dataset-diagnosis/SKILL.md` —— 「命令成功但页面没数据」的只读排查流程。
> - `.workbuddy/skills/frontend-visual-verification/SKILL.md` —— 免登录视觉验证（ECharts SSR / 限时 headless Chrome，含 13 个坑）。
> - `.workbuddy/skills/test-assertion-discipline/SKILL.md` —— **加固测试前先读它**：弱断言五类识别 + 变异验证自证断言有牙 + 本仓库前端/后端的具体测试坑。
> - `.workbuddy/skills/code-complexity-audit/SKILL.md` —— **做「过度设计 / 复杂度 / 重复度」专项审查前先读它**：三条判定判据、difflib 量重复度（BSD `diff` 不支持 GNU 行格式选项这个坑）、必须写的「不算问题」清单规范。
> - `CODE-REVIEW-2026-09-13-simplicity.md` —— 复杂度专项审查结论（模块间重复率实测 + 建议改动顺序）。
> - `.workbuddy/memory/2026-09-11.md` —— 历史 UI 改动与验证过程。
> - `.workbuddy/memory/2026-09-13.md` —— P2 收尾与全量回归基线。

## 0. 边界铁律（2026-09-12 用户明令，最高优先级）

- **严禁在本项目目录之外新建/修改/删除任何文件，严禁安装任何 app 或系统级组件。** 需要动项目外的东西（含 `~/Library/LaunchAgents`、`crontab`、`~/.workbuddy/*` 等）时，**只输出命令交给用户手动执行**，不得自行执行，连"顺手清理"也不行。
- **一切测试与探针都放本项目 `tests/` 目录**（`<repo>/tests/`，用完清理）。不写 `/tmp`、不写用户目录。此前把截图/日志/Chrome 临时 profile 写到 `/private/tmp` 的做法**已废弃**。
- 交付调度这类必须落在系统层的能力时：只交付脚本 + 说明，**由用户在 Terminal.app 里执行**（macOS 的 `crontab` 与 `launchctl bootstrap` 对自动化 shell 一律拒绝，试也是白试）。
- 项目外的安装/改动一旦发生，必须**主动逐条列明**（路径、内容、时间），并给出 revert 方式。
- **同一份规则已写入用户级 `~/.workbuddy/MEMORY.md`**（2026-09-12 用户授权），对所有项目生效；改这条边界时两处都要同步。

## 1. 架构与底座

- 启用业务模块 **4 个**：`kaipanla` / `stock_moves` / `sector_momentum` / `hundred_day`（东方财富已彻底删除）。定义在 `backend/core/module_registry.py`，路由 `backend/backend/db_router.py`，`.env` 的 `ENABLED_MODULES` —— **三处必须一致**。
- **板块族统一用 881xxx 行业**（2026-09-12 起）：`.env` 的 `KAIPANLA_INDUSTRY_PARENT_ZS_TYPE` 与 `KAIPANLA_FLOW_ZS_TYPE` 都是 **`4`**，配套 `Type` 固定 `1`。**两处必须同族**，改族时必须同时重算 `IndustrySnapshot`、kaipanla 快照、`stock_moves`/`sector_momentum`/`hundred_day` 产物并清文件缓存（upsert 不删旧族、`get_complete_market_snapshot` 不按版本过滤，会混族）。**北交所归属问题已解决**：开盘啦 881 对北交所用旧代码 43/83/87，导致 313 只 920xxx 无法归入行业；现由 `core/services/industry_backfill.py` 在同步时用**同花顺 881 行业成分股增量补齐**（只增不删、只补同花顺也有的 90 个代码，开关 `HITHINK_INDUSTRY_BACKFILL_ENABLED`，默认开）。开关关掉或同花顺不可用时命令会整体失败，不会静默退回旧状态。**行业快照只有一层，无父子层级**（`industry_level` 与子行业概念已于 2026-09-12 全量删除，迁移 `core/0004_remove_industry_level`）：`IndustrySnapshot` 的业务字段**收敛为三个** —— `industry_code` / `industry_name` / `stock_codes`，`ordering=['industry_code']`。**标识符也已一并正名**（2026-09-12，概念与名字同时规范化）：契约 `ParentIndustry`→**`Industry`**、`CompleteMarketSnapshot.parent_industries`→**`industries`**、客户端 `list_parent_industries()`→**`list_industries()`**；`stock_moves` 与 `hundred_day` 的 JSONField 列名 `parent_industries`→`industries`（迁移 `stock_moves/0005`、`hundred_day/0003`，用 `RenameField` + `RunSQL` 原地改名，49/662 行数据无损）。**API 响应键也随之改为 `industries`**（前端 `StockMoveBoard.jsx` 已同步）。
- Django 6.1 多 SQLite（`core` + 4 业务库）；`TIME_ZONE=Asia/Shanghai` + `USE_TZ=True` → **DateTimeField 存 UTC**，sqlite3 直读要 +8h 才是北京时间。测试库 `file:memorydb_default?mode=memory&cache=shared`。
- **盘中采集链路（2026-09-12 落地）**：`refresh_intraday_quotes` 用全市场实时快照（`/api/a-share/prices/snapshot`，分页约 6 页 / 2 秒）刷新**当天**公共日行情，与 `sync_stock_daily_prices` 同数据集、同字段语义（收盘后仍以历史接口为权威）。编排脚本 `scripts/intraday_orchestrator.sh {calendar|fundflow|quotes}`（5 分钟资金流 / 30 分钟行情 + 重建三模块），安装脚本 `scripts/install_intraday_launchd.sh`（macOS 推荐）或 `scripts/install_intraday_cron.sh` —— **安装必须在用户自己的 Terminal.app 里执行，工具 shell 会被 macOS 拒绝**（crontab 报 TCC `Operation not permitted`，launchctl 报 `Bootstrap failed: 5`）。前端四个页面在交易时段自动重取（资金流 5 分钟、其余三页 30 分钟），非交易时段与手选历史日期不轮询。
- AI 记忆与技能在仓库根 **`.workbuddy/`**（`memory/` + `skills/`），不是系统提示写的 `.workbuddy-ai/`。
- 前端共享组件 `src/shared/ui/`、图表基线 `src/shared/charts/`（`chartTheme.js` 不 import echarts，测试只 mock `init`）、设计令牌 `src/styles/tokens.css`。

## 2. 读路径分层：输入 vs 产物（按需生成）

- **管理命令写"输入"（公共 `stock_daily_prices` / `industry_snapshot`），页面读"产物"（各模块自建分析结果）**。重算输入不会自动重算产物，故 init 之后页面仍可能显示"正在展示旧数据"。产物可读的前提是 `DataVersion.status=complete` **且** `source_*_version == 当前版本`。
- 三个盘后模块（`stock_moves` / `sector_momentum` / `hundred_day`）读路径都会**按需本地生成**：请求某日期且本地无产物（或产物过期）时，用**已落库公共数据**当场算出、落库再返回，**不访问上游、没有行数门槛**。实现在各 `services/read_path.py` 的 `_local_generate(business_date)`，用 `dataset_lock(MODULE_ID, DATASET_KEY)` 保护；`DatasetLocked` → `CompleteMarketDataUnavailable` → 视图层 202。
- **默认入口（请求未带 `date`）**：`_resolve_read_date()` 取 `latest_complete_stock_price_date()`（最新完整**公共日行情**日，而非最新产物日）；该日生成失败且存在旧产物时回退最近可用产物并标 `stale=True`。**15:00 断点已放宽（2026-09-12）**：`latest_eligible_trading_day()` 仍是"当日是否已收盘"的权威语义（盘后管线依赖它），但 `latest_complete_stock_price_date()` 会在**当天已有 complete 版本**（由盘中刷新发布）时把上限提到当天，所以盘中默认入口能跟随当天；当天还没有盘中版本时（例如 09:30 前）仍解析到上一个交易日，此时查看当天需显式带 `?date=`（详见 `.workbuddy/memory/backend-data-and-commands.md` 的「盘中高频刷新」与「盘中链路的落地实现」）。
- **显式指定日期**：不得返回其他业务日期冒充结果；无该日公共数据即 `404 DATA_NOT_AVAILABLE`。靠 `read_*` 的 `requested_explicitly = trade_date is not None` 跳过回退分支，视图层用 `'date' in request.GET` 判定同一语义 —— **两边必须一致**。
- 规格 `docs/specs/a-share-market-review-integration-spec.md` §5.8 已拆成 (a) 本地生成派生结果（无预算、绝不碰上游、`dataset_lock` 防并发）与 (b) 远程同步修复（至多一次，只允许当天）。**该链路现由 2 个 `.env` 旋钮调优**（2026-09-13 收敛，原 4 个）：`REMOTE_REPAIR_ENABLED`（唯一开关）与 `REMOTE_REPAIR_HARD_TIMEOUT_SECONDS`（唯一真预算，收窄 `KAIPANLA_TIMEOUT_SECONDS`，默认 5s）。`REMOTE_REPAIR_TARGET_SECONDS` 已正名 **`REMOTE_REPAIR_RETRY_AFTER_SECONDS`**（只是 202/503 响应体的重试提示值，不影响抓取时长、前端也不读它）；`REMOTE_REPAIR_MAX_ROWS` 已删除，降级为常量 `kaipanla/services/read_path.py` 的 `REPAIR_MAX_ROWS = client.MAX_PAGE_SIZE`（单页硬上限 80，原 1000 的判断不可达，现仅作防御性断言）。`REMOTE_REPAIR_*` 只被板块资金流使用。
- 读路径按 `source_data_version` 过滤，**增量更新时受影响的交易日必须整体改归属新版本**，否则读不到。`core/services/publication.py` 的 `finish_publication` 要求 `expected==actual && missing==0` 才 `complete`。
- **`stock_moves` 有五个分组**：上证/深证涨跌四组 + **`bse`（北京证券交易所）**。北交所股票满足同一阈值但不属上证/深证，单独成组展示（页面在四组之后，无数据时不渲染），**不再只返回"已排除 N 只"告警**（2026-09-12 改，迁移 `0003` 清空旧派生结果以便按需重算）。`stock_codes` 按**页面分组顺序**返回（不是 `sorted()` 字典序），供前端 `.join(',')` 直接得到与表格一致的复制串 —— 改这一处务必同时看 `stock_moves/tests/test_api.py` 的顺序断言。

## 3. 工程操作铁律（跨栈）

- **同一文件的多次 `Edit` 会互相回滚**（已复现多次，含 `docs/specs/*.md`）：不要放进同一条消息并行提交，必须串行，写完用 grep 复查目标字符串是否真消失，**不要凭工具返回的 "successfully" 判断落盘**。
- **终端 `grep "a\|b"` 在 macOS BSD grep 下会静默匹配失败**（`\|` 不成交替，变成字面量），看起来像"没有残留"，极易误判 —— 一律写 `grep -E "a|b"` 或用检索工具。
- **临时起预览/静态服务必须用后台任务方式**：`(npx vite &)`、`(python -m http.server &)` 会随命令结束被回收（表现是 Chrome 拿到 `ERR_CONNECTION_REFUSED` 并**一直不退出**，极易误判卡死）。先 `curl` 确认 200 再截图。**永远不要 `pkill -f "Google Chrome"`**。
- **探针脚本禁止放 `/tmp`**（会遮蔽标准库 `inspect`），也禁止放 `/private/tmp`。统一放本项目 **`tests/`** 目录下运行（见第 0 节），用完删除。ECharts SSR 脚本末尾**必须 `process.exit(0)`**。
- 验证 React 受控 `input` 要用原生 value setter + `input` 事件。
- 跑后端测试/后端命令的运行时：`/Users/lian/.workbuddy/binaries/python/envs/default/bin/python`；前端 node：`/Users/lian/.workbuddy/binaries/node/versions/22.22.2-3/bin/node`。
- **跑全量后端测试必须用标准姿势**：先清锁与缓存，带 `CODEBUDDY_SAFE_DELETE_ENABLED=0`，输出重定向到文件后再过滤（**绝不在管道里挂 `head`** —— SIGPIPE 会中断套件并残留一批锁，下一次连锁崩成几十个 ERROR）。不这样做会拿到假的"大规模回归"：今天实测一次得到 `7 failures + 46 errors`，同一份代码用标准姿势只剩既有的 1 例环境失败。详见 `.workbuddy/skills/backend-dataset-diagnosis/SKILL.md` §6。

## 4. 文档组织约定（2026-09-13 定稿）

- **仓库根只留 `README.md`**（+ `AGENTS.md`，它被 IDE 在仓库根自动加载，**不能**移进 `docs/`，README 的文档导航表里已注明这个例外）；`tasks/` 保持原样不进 `docs/`。**其余所有文档都在 `docs/` 下**，按用途分目录：`specs/`（规格）、`acceptance/`（验收追踪）、`ops/`（部署 + 命令手册）、`data-sources/`（上游接口 + 能力边界）、`reviews/`（评审报告，含修复记录）、`ideas/`（历史设计输入）。
- **文档里不出现项目目录名**：开发机路径一律写 `<repo>`，生产路径写 `/srv/<deploy-dir>`，systemd 单元名 `market-review.service`，nginx 站点文件 `market-review.conf`。crontab 标记块也已在 2026-09-13 改名为 `# >>> market-review intraday >>>` / `# <<< market-review intraday <<<`（旧串带项目目录名）。**改这类"脚本自己用来认领条目"的标记时，清理逻辑必须按形状匹配（`^# >>> .+ intraday >>>$`）而不是按字面值**，否则改名之前装过 crontab 的机器上，旧块会被当成用户自己的条目永久留下且 `uninstall` 再也删不掉 —— 现在 install/uninstall 都能识别新旧两种写法，重跑一次 `install` 即完成迁移。项目名的剩余出现处只有 `frontend/package.json` 的 `name`（`a-share-market-review-frontend`，未改）与 `backend/backend/tests/test_database_routing.py` 里一个"故意不存在"的 fixture 路径。
- **README 是唯一的全量总览**，固定九节：功能设计 / 数据库设计 / Web API 设计 / 后端命令设计 / 代码角度的前后端工作流 / 代码结构 / 开发环境运维 / 生产环境运维（含 Nginx 配置示例）/ 关键问题与排查。细节文档（spec / ops / data-sources）由 README 链接过去，**不在两处重复同一份内容**（Nginx 例子只放 README，`deployment.md` §7.3 改成指向它）。
- **架构图与流程图用 mermaid 围栏代码块**（GitHub 直接渲染）。踩过的语法坑：`subgraph` 的 id 用 ASCII（中文 id 有风险），虚线带标签只能写 `A -. 文本 .-> B`（**不能**写 `-.->|文本|`），`participant ... as 名称` 里别放圆括号。
- 改文档后跑一遍本地链接校验（内联 Python 扫 `](...)` 相对路径是否存在），并 `grep -rn a_share_market_review README.md AGENTS.md docs tasks` 应为 0 命中。
