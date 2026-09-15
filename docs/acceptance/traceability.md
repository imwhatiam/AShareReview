# 规格验收追踪矩阵

- **规格来源：** `docs/specs/integration-spec.md`
- **标准数量：** 113。计数规则：`AC-SRC-000`、`AC-SRC-000A`、`AC-SRC-000B`、`AC-SRC-000C` 是四条独立标准，不能按前缀合并计数。
- **证据状态含义：** “自动化”表示已有仓库测试或静态检查；“人工待执行”表示必须在所有者提供的已部署 HTTPS 环境中执行，当前没有声称已完成。

**维护约定：** 规格里每新增一条 `AC-*`，必须在本文件补一行映射，并同步“标准数量”。反向检查方式：从规格与本文各抓取一遍 `AC-[A-Z]+-\d{3}[A-Z]?`（**必须**带可选字母后缀，否则 `AC-SRC-000A/B/C` 会被并进 `AC-SRC-000` 而少算 3 条），两者集合必须相等；同时本文件的映射表行数应等于该集合大小。

## 回归基线

| 目标 | 命令 | 最近一次结果 |
| --- | --- | --- |
| 后端全量 | `manage.py test`（先从 `backend/` 清 `data/locks/*.lock` 与 `cache/`，并带 `CODEBUDDY_SAFE_DELETE_ENABLED=0`；输出重定向到文件后再过滤，不要接 `head`） | `Ran 440 tests in 8.105s` → `FAILED (failures=1)`；唯一失败是下面「已知缺口」第 1 条的环境项，不是代码回归 |
| 定向回归 | `manage.py test backend.tests.test_module_isolation backend.tests.test_security_settings backend.tests.test_source_policy` | 14 tests passed |
| 开盘啦适配器与安全设置 | `manage.py test core.tests.test_kaipanla_industry_adapter kaipanla.tests.test_fetcher backend.tests.test_security_settings` | `Ran 28 tests`；唯一失败是 `test_security_settings` 的环境项。覆盖三类 KPL 字段为空时省略 / 非空时携带、两个端点共用请求头与错误码的契约 |
| 模块隔离矩阵 | `./scripts/check_module_matrix.sh` | 四种 `core + 单业务 App` 配置的 check、迁移计划、命令/URL 发现及单 App 测试通过；未请求真实上游 |
| 配置与迁移一致性 | `manage.py check` 与 `manage.py makemigrations --check --dry-run` | 均通过；`No changes detected` |
| 前端全量 | `npm test`（= `vitest run`）/ `npm run lint` / `npm run build` | 19 个测试文件 / 153 条用例全部通过；`eslint src --max-warnings=0` 无输出（退出码 0）；`vite build` 成功 |
| 开盘啦受控真实上游验证 | 携带当前 `.env` 三项 KPL 配置 / 显式省略三个字段 | 两种模式均可完成资金流完整分页及行业—股票列表链路；股票列表使用库里已有的快照 |

**关于后端那 1 例失败。** `backend/backend/tests/test_security_settings.py::test_runtime_security_settings_are_safe_by_default` 只在生产口径的 `.env`（`DJANGO_DEBUG=false`）下真正执行断言。本机 `.env` 是生产口径，而 `DJANGO_SECRET_KEY` 仍是 `.env.example` 的占位符，于是它断言 `assertNotIn('replace-with', settings.SECRET_KEY)` 并失败；换成真实密钥即通过，把 `.env` 切回 `DJANGO_DEBUG=true` 则 `skipTest`。**它是环境驱动的，判断代码是否回归时应把这 1 例扣除。**

前端三条命令可用仓库内 managed node 直调等价入口：`node node_modules/vitest/vitest.mjs run`、`node node_modules/eslint/bin/eslint.js src`、`node node_modules/vite/bin/vite.js build`，与 `npm test` / `npm run lint` / `npm run build` 是同一份配置与同一批文件。

真实网页/API、真实上游采集及部署环境验收尚未执行，逐条清单见下文「待所有者提供环境后执行的受控运行时验收」。


## 自动化/人工证据映射

> **路径口径**：本表同时出现两种写法，指向的是同一个文件 —— `kaipanla/tests/test_api.py` 是相对 `backend/`，`backend/backend/tests/test_module_isolation.py` 是相对仓库根；前端一律以 `frontend/` 开头（相对仓库根）。新增行请统一用相对仓库根的写法（`backend/…`、`frontend/…`），便于直接复制到终端。

| 验收标准 | 证据 | 状态 |
| --- | --- | --- |
| AC-UI-001 | `frontend/src/app/AppShell.test.jsx`（匿名态不请求业务数据） | 自动化 |
| AC-UI-002 | `frontend/src/app/AppShell.test.jsx`（登录后默认开盘啦） | 自动化；真实浏览器待执行 |
| AC-UI-003 | `frontend/src/app/AppShell.test.jsx` | 自动化 |
| AC-UI-004 | `frontend/src/app/AppShell.test.jsx`（不渲染数据源切换器） | 自动化 |
| AC-UI-005 | `frontend/src/app/AppShell.test.jsx`、`backend/backend/tests/test_module_isolation.py` | 自动化；真实路由待执行 |
| AC-UI-006 | 各模块页面测试的局部错误状态断言 | 自动化 |
| AC-UI-007 | `frontend/src/shared/DataState.test.jsx`、各模块页面测试 | 自动化 |
| AC-UI-008 | `frontend/src/shared/DataState.test.jsx` | 自动化 |
| AC-UI-009 | `frontend/src/shared/useResource.test.jsx`（`never fetches on its own, however long the page stays open` 反轮询守卫、`fetches again when refresh() is called`、`surfaces a failed refresh as an error instead of keeping the old data`）、`frontend/src/shared/RefreshStamp.test.jsx`（按钮角色 + 点击回调）、四个页面测试的 `re-requests ... when「更新于」is clicked`、`frontend/src/index.css`（`.updated-at` 手型光标与悬停反馈） | 自动化；真实浏览器已验证（headless Chrome 计算样式：`cursor: pointer`、与日期控件同高 37.2px；点击后 mock fetch 计数 1 → 2，URL 相同） |
| AC-UI-010 | `frontend/src/shared/useResource.test.jsx`（`reports when the data was written, not when it was fetched` 原样透传信封字段、`has no timestamp at all when the envelope carries no data time`）、`frontend/src/shared/RefreshStamp.test.jsx`、四个页面测试的 `re-requests ... when「更新于」is clicked`（断言胶囊上的时刻是信封给的那个值）；后端侧同一契约：`core/tests/test_api_contract.py`（ISO 往返 + 没有时刻时为 `null`）、`hundred_day/tests/test_fallback.py`（`test_the_data_time_is_reported_from_both_database_and_cache`）、`kaipanla/tests/test_queries.py`（`test_the_write_stamp_comes_from_the_newest_slot`）、`kaipanla/tests/test_fallback.py`（缓存命中同样带时刻）、`kaipanla/tests/test_api.py` | 自动化；变异验证：把时刻改回 `Date.now()` → 前端 5 个文件 6 条用例失败；把读路径的 `created_at` 置空 → `hundred_day` 那一条失败；只在缓存分支漏传 → 3 条失败；把「最新槽」改成「最旧槽」→ 4 条失败 |
| AC-MOD-001 | `backend/backend/tests/test_module_isolation.py::test_business_apps_do_not_import_each_other` | 自动化 |
| AC-MOD-002 | `test_business_models_do_not_declare_cross_app_relations`、`test_database_routing.py` | 自动化 |
| AC-MOD-003 | `test_each_business_app_has_its_own_required_runtime_artifacts` | 自动化 |
| AC-MOD-004 | `scripts/check_module_matrix.sh` | 自动化 |
| AC-MOD-005 | `scripts/check_module_matrix.sh` | 自动化；上游 dry-run 待获准 |
| AC-MOD-006 | `backend/core/tests/test_admin_readonly.py`、单模块矩阵 | 自动化 |
| AC-MOD-007 | `test_business_models_do_not_declare_cross_app_relations`、`test_database_routing.py` | 自动化 |
| AC-CORE-001 | `core/tests/test_sync_daily_prices_commands.py` | 自动化 |
| AC-CORE-002 | `core/tests/test_market_models.py`、`test_sync_daily_prices_commands.py` | 自动化 |
| AC-CORE-003 | 三个分析 App 的 `test_models.py` 与 `test_command.py` | 自动化 |
| AC-CORE-004 | `core/tests/test_market_data_services.py`；覆盖边界：`core/tests/test_calendar_services.py::HolidayTableCoverageTests`、`core/tests/test_modules_api.py::test_health_carries_the_holiday_table_coverage_contract`、`core/tests/test_app_bootstrap.py` | 自动化 |
| AC-CORE-005 | `core/tests/test_market_models.py` | 自动化 |
| AC-CORE-006 | `core/tests/test_sync_industries_commands.py` | 自动化 |
| AC-CORE-007 | `core/tests/test_sync_daily_prices_commands.py`、`test_sync_industries_commands.py` | 自动化 |
| AC-CORE-008 | `core/tests/test_sync_daily_prices_commands.py`（写入前校验：截断/覆盖率不足 ⇒ 整批不写入，失败只进 `core.management` 日志）、`core/tests/test_management_contract.py` | 自动化 |
| AC-SRC-000 | `core/tests/test_hithink_adapter.py`、`backend/backend/tests/test_source_policy.py` | 自动化 |
| AC-SRC-000A | `core/tests/test_hithink_adapter.py`、`test_sync_daily_prices_commands.py` | 自动化 |
| AC-SRC-000B | `core/tests/test_kaipanla_industry_adapter.py`、`test_sync_industries_commands.py`；真实上游已验证 | 自动化；真实上游已验证（股票列表使用库里已有的快照） |
| AC-SRC-000C | `core/tests/test_industry_backfill.py`（只补缺的、忽略本地不认识的代码、不删开盘啦成员、跳过同花顺没有的代码、开关可关、上游异常向上抛、同一只被两个行业补到只计一次）、`core/tests/test_sync_industries_commands.py`（端到端接线） | 自动化；真实上游已验证（added=325，未映射 313→0） |
| AC-SRC-001 | `backend/backend/tests/test_source_policy.py` | 自动化 |
| AC-SRC-002 | `backend/backend/tests/test_security_settings.py`、`.gitignore` | 自动化；人工代码审查 |
| AC-SRC-003 | `kaipanla/tests/test_fetcher.py`、`core/tests/test_kaipanla_industry_adapter.py`、`backend/backend/tests/test_security_settings.py`；真实上游已验证 | 自动化；真实上游已验证 |
| AC-SRC-005 | `core/tests/test_management_contract.py`、日志脱敏相关测试 | 自动化 |
| AC-SRC-006 | `core/tests/test_hithink_adapter.py`、资金流 fetcher 测试 | 自动化 |
| AC-SRC-007 | `core/tests/test_sync_reference_commands.py`（截断被拒 / 正常波动放行 / dry-run 同样校验） | 自动化 |
| AC-FLOW-001 | `kaipanla/tests/test_api.py`；"固定交易时间轴"的口径由 `kaipanla/tests/test_queries.py`（完整时段 50 槽 / 曲线只到最后一个已采集时点）钉住 | 自动化 |
| AC-FLOW-002 | `kaipanla/tests/test_api.py` | 自动化 |
| AC-FLOW-003 | `kaipanla/tests/test_api.py` | 自动化 |
| AC-FLOW-004 | `kaipanla/tests/test_queries.py` | 自动化 |
| AC-FLOW-005 | `kaipanla/tests/test_queries.py` | 自动化 |
| AC-FLOW-006 | `kaipanla/tests/test_command.py`（采集不全 ⇒ 非零退出、一行不写、只留 `kaipanla_collection_incomplete`）、`test_writer.py` | 自动化 |
| AC-FLOW-009 | `frontend/src/features/kaipanla/KaipanlaPage.test.jsx`（`re-derives the default selections from the refreshed rankings` 钉住"点「更新于」刷新后按新榜单重算"、`switches dates and windows, re-deriving the default selections from each response` 钉住切窗口/切日期重算）、`sector-flow/flowView.test.jsx` 与 `sector-flow/SectorFlowView.test.jsx`（无关重渲染不重算，钉住"手动勾选在同一份数据内有效"） | 自动化 |
| AC-FLOW-010 | `kaipanla/tests/test_fallback.py`（`KaipanlaExpectedSnapshotDateTests` 钉住 09:30/开盘前/休市日三个时钟口径、`_today_is_still_collecting` 钉住收盘前后分岔；`test_default_entry_follows_the_newest_stored_snapshot` 钉住"当天有快照即显示当天"）、`test_api.py`（202 与 stale 两条端点行为） | 自动化 |
| AC-FLOW-011 | `kaipanla/tests/test_fallback.py`（`KaipanlaReadPathHasNoUpstreamTests` 钉住读路径不 import 上游、修复词表已删；`test_a_new_collected_slot_is_not_served_from_the_previous_slot_cache` 钉住缓存身份随新槽改变）、`test_models.py`（模块只拥有这一张表） | 自动化 |
| AC-MOVE-001 | `stock_moves/tests/test_analysis.py` | 自动化 |
| AC-MOVE-002 | `stock_moves/tests/test_analysis.py` | 自动化 |
| AC-MOVE-003 | `stock_moves/tests/test_analysis.py` | 自动化 |
| AC-MOVE-004 | `stock_moves/tests/test_analysis.py` | 自动化 |
| AC-MOVE-005 | `stock_moves/tests/test_analysis.py`、`test_api.py` | 自动化 |
| AC-MOVE-006 | `frontend/src/features/stock-moves/StockMovesPage.test.jsx` | 自动化；真实剪贴板待执行 |
| AC-MOVE-007 | `stock_moves/tests/test_api.py` | 自动化 |
| AC-MOVE-008 | `stock_moves/tests/test_analysis.py` | 自动化 |
| AC-MOVE-009 | `stock_moves/tests/test_analysis.py`、前端页面测试 | 自动化 |
| AC-MOVE-010 | `frontend/src/features/stock-moves/StockMovesPage.test.jsx`（北交所整行保留 / 单侧为空） | 自动化 |
| AC-MOVE-011 | `frontend/src/features/stock-moves/StockMovesPage.test.jsx`（`btn--ghost`、图标在文字后）、`frontend/src/index.css`（`.move-list` 三列与 80rem/40rem 降级） | 自动化；几何实测见 `.workbuddy/skills/frontend-visual-verification/SKILL.md` |
| AC-MOM-001 | `sector_momentum/tests/test_analysis.py` | 自动化 |
| AC-MOM-002 | `sector_momentum/tests/test_analysis.py` | 自动化 |
| AC-MOM-003 | `sector_momentum/tests/test_analysis.py` | 自动化 |
| AC-MOM-004 | `sector_momentum/tests/test_analysis.py` | 自动化 |
| AC-MOM-005 | `sector_momentum/tests/test_analysis.py`、`test_api.py` | 自动化 |
| AC-MOM-006 | `sector_momentum/tests/test_analysis.py` | 自动化 |
| AC-MOM-007 | `sector_momentum/tests/test_command.py`（同天重跑 = 覆盖）、`test_models.py`（`business_date` 唯一约束） | 自动化 |
| AC-MOM-008 | `sector_momentum/tests/test_analysis.py`、前端页面测试 | 自动化 |
| AC-MOM-009 | `frontend/src/shared/charts/chartTheme.test.js`（竖排 / 三子柱 / 三轴 / 名次从左到右）、`HundredDayPage.test.jsx` 同款明细写法 | 自动化 |
| AC-MOM-010 | `frontend/src/index.css`（`.momentum-grid` 与 64rem 单列断点）、`MomentumChart`/页面测试 | 自动化 |
| AC-HD-001 | `hundred_day/tests/test_analysis.py` | 自动化 |
| AC-HD-002 | `hundred_day/tests/test_analysis.py` | 自动化 |
| AC-HD-003 | `hundred_day/tests/test_analysis.py` | 自动化 |
| AC-HD-004 | `hundred_day/tests/test_analysis.py` | 自动化 |
| AC-HD-005 | `hundred_day/tests/test_analysis.py` | 自动化 |
| AC-HD-006 | `hundred_day/tests/test_analysis.py` | 自动化 |
| AC-HD-007 | `hundred_day/tests/test_analysis.py`、`test_api.py` | 自动化 |
| AC-HD-008 | `frontend/src/features/hundred-day/HundredDayPage.test.jsx` | 自动化 |
| AC-HD-009 | `hundred_day/tests/test_command.py`（同天重跑 = 覆盖）、`test_models.py`（`business_date` 唯一约束） | 自动化 |
| AC-HD-010 | `hundred_day/tests/test_analysis.py`、前端页面测试 | 自动化 |
| AC-HD-011 | `frontend/src/features/hundred-day/HundredDayPage.test.jsx`（新高降序 / 新低升序 / null 垫底 / 同值稳定） | 自动化 |
| AC-FALL-001 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-002 | `core/tests/test_file_cache.py`、各模块 fallback 测试 | 自动化 |
| AC-FALL-003 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-004 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-005 | `core/tests/test_locking.py`、fallback 测试 | 自动化 |
| AC-FALL-006 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-007 | 同步命令测试与各模块 fallback 测试 | 自动化 |
| AC-FALL-008 | `core/tests/test_file_cache.py`（缓存身份不匹配即视为未命中） | 自动化 |
| AC-FALL-009 | `core/tests/test_locking.py` | 自动化 |
| AC-FALL-010 | `stock_moves/tests/test_fallback.py`、`sector_momentum/tests/test_fallback.py`、`hundred_day/tests/test_fallback.py`（`*_never_starts_remote_full_market_sync`） | 自动化 |
| AC-FALL-011 | `core/tests/test_market_data_services.py`、各模块 `test_fallback.py` | 自动化 |
| AC-FALL-012 | 各模块 `test_api.py`（显式日期返回 `404 DATA_NOT_AVAILABLE`） | 自动化 |
| AC-TIME-001 | `core/tests/test_market_data_services.py`、模块命令测试 | 自动化 |
| AC-TIME-002 | `core/tests/test_market_data_services.py` | 自动化 |
| AC-TIME-003 | `core/tests/test_market_data_services.py` | 自动化 |
| AC-TIME-004 | `core/tests/test_market_data_services.py`、模块 fallback 测试 | 自动化 |
| AC-TIME-005 | `core/tests/test_market_data_services.py` | 自动化 |
| AC-API-001 | `backend/backend/tests/test_module_isolation.py`、模块 API 测试 | 自动化 |
| AC-API-002 | `core/tests/test_api_contract.py`、模块 API 测试 | 自动化 |
| AC-API-003 | `core/tests/test_api_contract.py`、模块 API 测试 | 自动化 |
| AC-API-004 | `core/tests/test_session_api.py`、模块 API 测试 | 自动化 |
| AC-API-005 | `core/tests/test_api_contract.py`、模块 fallback 测试 | 自动化 |
| AC-API-006 | 模块 fallback/API 测试 | 自动化 |
| AC-API-007 | 模块 API 测试 | 自动化 |
| AC-API-008 | `scripts/check_module_matrix.sh` | 自动化 |
| AC-SEC-001 | `backend/backend/tests/test_security_settings.py` | 自动化 |
| AC-SEC-002 | `core/tests/test_session_api.py` | 自动化 |
| AC-SEC-003 | `core/tests/test_admin_readonly.py`（非 staff 访问 `/admin/` 被重定向到登录）、Django admin 默认权限 | 自动化；真实反向代理待执行 |
| AC-SEC-004 | `backend/backend/tests/test_security_settings.py`、`.gitignore`、发布前人工检查 | 自动化/人工 |
| AC-SEC-005 | `core/tests/test_api_contract.py`、模块 API 参数测试、React 默认转义 | 自动化 |
| AC-SEC-006 | `backend/backend/tests/test_security_settings.py`、`docs/ops/deployment.md` | 自动化/人工 |
| AC-OPS-001 | `core/tests/test_admin_readonly.py`（staff 可读公共数据页、每个注册页都拒绝新增） | 自动化 |
| AC-OPS-002 | `core/tests/test_command_logging.py`（开始/进度/结束/失败共用批次 ID、失败原因留在命令行）、各模块命令测试（失败只进 `core.management` 日志） | 自动化 |
| AC-OPS-003 | `core/tests/test_locking.py`、各模块命令测试 | 自动化 |
| AC-OPS-004 | `core/tests/test_command_logging.py` 与 `docs/ops/deployment.md` | 自动化/人工 |
| AC-OPS-005 | `docs/ops/deployment.md` | 人工（无自动化任务） |
| AC-OPS-006 | `core/tests/test_locking.py`（死持有者立即回收 / 活持有者永不回收 / 跨主机按阈值 / 损坏锁按阈值 / 阈值 0 只允许死持有者 / 释放不删他人重建的锁） | 自动化 |

## 已知缺口（未闭环项）

以下缺口**当前没有自动化证据**，也不在上面/下面的运行时验收清单里。它们不阻塞使用，但判断"是否回归"时要按环境项或已知项扣除。

| # | 缺口 | 现状与影响 | 处置方向 |
| --- | --- | --- | --- |
| 1 | 本机 `.env` 的 `DJANGO_SECRET_KEY` 仍是 `.env.example` 的占位符 | `backend/backend/tests/test_security_settings.py::test_runtime_security_settings_are_safe_by_default` 持续红一条 —— 该用例只在生产口径的 `.env` 下才真跑断言。**这是环境项，不是代码回归** | 换成真实随机长值即通过；会话签名会随之失效，需重新登录 |
| 2 | 登录无速率限制 / 账号锁定 | 需要引入新依赖（如 `django-axes`） | 由所有者决定是否引入 |
| 3 | `frontend/src/index.css` 三处无自动化断言：`:focus-visible`、`@media (max-width: 40rem)`、`overflow-x: auto` | 读 CSS 文本断子串既过严又过松、且依赖 CWD，因此不写这类用例；这三处的回归只能靠截图人眼确认 | 改动这三处时不要指望测试兜底 |
| 4 | 真实网页 / API、真实上游采集与部署环境验收 | 尚未执行，逐条清单见下一节 | 需要所有者提供已部署环境 |

`kaipanla` 表 8 个只写不读的列（`change_pct` / `main_buy` / … ）已由所有者决定**保留**（采集型系统先把上游观测值落库备查；字段顶部有注释说明），**不算缺口**。

## 待所有者提供环境后执行的受控运行时验收

以下检查需要所有者提供已部署 HTTPS 服务地址、测试账号，并明确允许访问该环境后才能执行。

1. 未登录访问业务页和 `/api/<app>/`，确认跳转/`401`，且不触发业务数据请求。
2. 登录后确认默认打开“板块资金流 → 开盘啦”，四个一级 Tab、键盘导航、窄屏横向滚动及状态提示均可用，且页面不出现数据源切换控件。
3. 在 Django admin 中以普通用户和 staff 用户分别验证权限与数据展示。
4. 使用真实可用缓存/旧快照验证 stale、partial、`DATA_PREPARING` 以及模块间隔离。
5. 由所有者决定是否允许开盘啦的受控上游 dry-run；上游被屏蔽时只验证预期失败语义，不绕过限制、不重试规避。
6. 验证 HTTPS、域名白名单、CSRF 可信来源、Django admin 静态文件和反向代理路由。

完成上述检查后，应在本文件补充服务地址（如可公开）、执行时间、操作者、使用的非敏感测试账号标识和结果，而不是把凭据写入仓库。
