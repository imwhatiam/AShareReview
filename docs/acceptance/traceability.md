# 规格验收追踪矩阵

- **规格来源：** `docs/specs/integration-spec.md`
- **基准日期：** 2026-09-12
- **标准数量：** 109（早期任务描述中的“95 条”“98 条”“106/107 条”均已过时。109 = 规格与本文双向闭合的实测值，计数规则见下方维护约定：`AC-SRC-000`、`AC-SRC-000A`、`AC-SRC-000B`、`AC-SRC-000C` 是**四条独立标准**，不能按前缀合并计数）
- **证据状态含义：** “自动化”表示已有仓库测试或静态检查；“人工待执行”表示必须在所有者提供的已部署 HTTPS 环境中执行，当前没有声称已完成。

**维护约定：** 规格里每新增一条 `AC-*`，必须在本文件补一行映射，并同步“标准数量”。反向检查方式：从规格与本文各抓取一遍 `AC-[A-Z]+-\d{3}[A-Z]?`（**必须带可选字母后缀**，否则 `AC-SRC-000A/B/C` 会被并进 `AC-SRC-000` 而少算 3 条），两者集合必须相等；同时本文件的映射表行数应等于该集合大小（2026-09-12 曾出现规格 104 / 本文 96、缺口 8 条全是当日新增项的情况）。

## 已运行的回归证据（2026-09-09，全量基线见下一小节）

> 下表是 2026-09-09 当次记录；除“最近一次全量基线”外未在 2026-09-12 / 2026-09-13 重跑。

| 验证 | 结果 |
| --- | --- |
| `python manage.py test backend.tests.test_module_isolation backend.tests.test_security_settings backend.tests.test_source_policy` | 14 tests passed |
| `./scripts/check_module_matrix.sh` | 四种 `core + 单业务 App` 配置的 check、迁移计划、命令/URL 发现及单 App 测试通过；未请求真实上游 |
| `python manage.py check` 与 `python manage.py makemigrations --check --dry-run` | 均通过；没有待生成迁移 |
| `python manage.py test`（清锁清缓存后） | 见下方“最近一次全量基线” |
| 前端 `npm test -- --run`、`npm run lint`、`npm run build` | 见下方“最近一次全量基线” |
| 开盘啦受控真实上游验证（携带当前 `.env` 三项 KPL 配置 / 显式省略三个字段） | 两种模式均可完成资金流完整分页及行业—股票列表链路；股票列表使用已发布的快照。 |
| `python manage.py test core.tests.test_kaipanla_industry_adapter kaipanla.tests.test_fetcher backend.tests.test_security_settings` | 16 tests passed；覆盖三类 KPL 字段为空时省略、非空时携带的契约。 |

### 最近一次全量基线

以该小节的数字为准；本文其他位置若出现更早的数字，视为历史记录。

| 目标 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量 | `manage.py test`（先从 `backend/` 清 `data/locks/*.lock` 与 `cache/`，并带 `CODEBUDDY_SAFE_DELETE_ENABLED=0`；输出**重定向到文件后再过滤**，不要接 `head`） | 2026-09-13：`Ran 395 tests in 36.664s` → `OK (skipped=1)`；0 失败、0 错误，跑完 `data/locks/` 为空 |
| 迁移一致性 | `manage.py makemigrations --check --dry-run` | 2026-09-13：`No changes detected`（没有待生成的迁移） |
| 前端全量 | `npm test`（= `vitest run`）/ `npm run lint` / `npm run build` | 2026-09-13：19 个测试文件 / 150 条用例全部通过；`eslint src` 无任何输出（退出码 0）；`vite build` 成功（658 modules transformed，仅保留既有的大 chunk 提示） |

> **上一次记录的“唯一的既有失败”已经不存在了。** `backend/backend/tests/test_security_settings.py::test_runtime_security_settings_are_safe_by_default` 现在会在本机 `.env` 是调试口径（`DJANGO_DEBUG=true`）时 `skipTest` 并说明原因，只在生产口径的 `.env` 下才真正执行那组断言 —— 即上表里的 `skipped=1`。它原先“在任何用本地调试配置的机器上都会失败”的环境耦合已消除，所以 2026-09-13 这一次是**真绿**：失败集合为空，不存在需要按“既有失败”扣除的条目。
>
> 前端三条命令本次是用仓库内 managed node 直调等价的入口跑的（`node node_modules/vitest/vitest.mjs run`、`node node_modules/eslint/bin/eslint.js src`、`node node_modules/vite/bin/vite.js build`），与 `npm test` / `npm run lint` / `npm run build` 是同一份配置与同一批文件。

真实网页/API、真实上游采集及部署环境验收仍未执行，原因和后续步骤见下文“待所有者提供环境后执行的受控运行时验收”。


## 自动化/人工证据映射

> **路径口径**：本表同时出现两种写法，指向的是同一个文件 —— `kaipanla/tests/test_api.py` 是**相对 `backend/`**，`backend/backend/tests/test_module_isolation.py` 是**相对仓库根**；前端一律以 `frontend/` 开头（相对仓库根）。新增行请统一用**相对仓库根**的写法（`backend/…`、`frontend/…`），便于直接复制到终端。

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
| AC-MOD-001 | `backend/backend/tests/test_module_isolation.py::test_business_apps_do_not_import_each_other` | 自动化 |
| AC-MOD-002 | `test_business_models_do_not_declare_cross_app_relations`、`test_database_routing.py` | 自动化 |
| AC-MOD-003 | `test_each_business_app_has_its_own_required_runtime_artifacts` | 自动化 |
| AC-MOD-004 | `scripts/check_module_matrix.sh` | 自动化 |
| AC-MOD-005 | `scripts/check_module_matrix.sh` | 自动化；上游 dry-run 待获准 |
| AC-MOD-006 | `backend/core/tests/test_admin_status.py`、单模块矩阵 | 自动化 |
| AC-MOD-007 | `test_business_models_do_not_declare_cross_app_relations`、`test_database_routing.py` | 自动化 |
| AC-CORE-001 | `core/tests/test_sync_daily_prices_commands.py` | 自动化 |
| AC-CORE-002 | `core/tests/test_market_models.py`、`test_sync_daily_prices_commands.py` | 自动化 |
| AC-CORE-003 | 三个分析 App 的 `test_models.py` 与 `test_command.py` | 自动化 |
| AC-CORE-004 | `core/tests/test_market_data_services.py` | 自动化 |
| AC-CORE-005 | `core/tests/test_market_models.py` | 自动化 |
| AC-CORE-006 | `core/tests/test_sync_industries_commands.py` | 自动化 |
| AC-CORE-007 | `core/tests/test_sync_daily_prices_commands.py`、`test_sync_industries_commands.py` | 自动化 |
| AC-CORE-008 | `core/tests/test_dataset_models.py`、同步命令测试 | 自动化 |
| AC-SRC-000 | `core/tests/test_hithink_adapter.py`、`backend/backend/tests/test_source_policy.py` | 自动化 |
| AC-SRC-000A | `core/tests/test_hithink_adapter.py`、`test_sync_daily_prices_commands.py` | 自动化 |
| AC-SRC-000B | `core/tests/test_kaipanla_industry_adapter.py`、`test_sync_industries_commands.py`；2026-09-09 真实上游验证 | 自动化；真实上游已验证（股票列表使用已发布的快照） |
| AC-SRC-000C | `core/tests/test_industry_backfill.py`（只补缺的、忽略本地不认识的代码、不删开盘啦成员、跳过同花顺没有的代码、开关可关、上游异常向上抛、同一只被两个行业补到只计一次）、`core/tests/test_sync_industries_commands.py`（端到端接线） | 自动化；2026-09-12 真实上游已验证（added=325，未映射 313→0） |
| AC-SRC-001 | `backend/backend/tests/test_source_policy.py` | 自动化 |
| AC-SRC-002 | `backend/backend/tests/test_security_settings.py`、`.gitignore` | 自动化；人工代码审查 |
| AC-SRC-003 | `kaipanla/tests/test_fetcher.py`、`core/tests/test_kaipanla_industry_adapter.py`、`backend/backend/tests/test_security_settings.py`；2026-09-09 真实上游验证 | 自动化；真实上游已验证 |
| AC-SRC-005 | `core/tests/test_management_contract.py`、日志脱敏相关测试 | 自动化 |
| AC-SRC-006 | `core/tests/test_hithink_adapter.py`、资金流 fetcher 测试 | 自动化 |
| AC-SRC-007 | `core/tests/test_sync_reference_commands.py`（截断被拒 / 正常波动放行 / dry-run 同样校验） | 自动化 |
| AC-FLOW-001 | `kaipanla/tests/test_api.py` | 自动化 |
| AC-FLOW-002 | `kaipanla/tests/test_api.py` | 自动化 |
| AC-FLOW-003 | `kaipanla/tests/test_api.py` | 自动化 |
| AC-FLOW-004 | `kaipanla/tests/test_queries.py` | 自动化 |
| AC-FLOW-005 | `kaipanla/tests/test_queries.py` | 自动化 |
| AC-FLOW-006 | `kaipanla/tests/test_publication.py`、`test_command.py` | 自动化 |
| AC-FLOW-009 | `frontend/src/features/kaipanla/KaipanlaPage.test.jsx`、`sector-flow/flowView.test.jsx` | 自动化 |
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
| AC-MOM-007 | `sector_momentum/tests/test_command.py`、`test_models.py` | 自动化 |
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
| AC-HD-009 | `hundred_day/tests/test_command.py`、`test_models.py` | 自动化 |
| AC-HD-010 | `hundred_day/tests/test_analysis.py`、前端页面测试 | 自动化 |
| AC-HD-011 | `frontend/src/features/hundred-day/HundredDayPage.test.jsx`（新高降序 / 新低升序 / null 垫底 / 同值稳定） | 自动化 |
| AC-FALL-001 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-002 | `core/tests/test_file_cache.py`、各模块 fallback 测试 | 自动化 |
| AC-FALL-003 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-004 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-005 | `core/tests/test_locking.py`、fallback 测试 | 自动化 |
| AC-FALL-006 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-007 | 同步、发布和 fallback 测试 | 自动化 |
| AC-FALL-008 | `core/tests/test_publication.py`、模块发布测试 | 自动化 |
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
| AC-SEC-003 | `core/tests/test_admin_status.py`、Django admin 默认权限 | 自动化；真实反向代理待执行 |
| AC-SEC-004 | `backend/backend/tests/test_security_settings.py`、`.gitignore`、发布前人工检查 | 自动化/人工 |
| AC-SEC-005 | `core/tests/test_api_contract.py`、模块 API 参数测试、React 默认转义 | 自动化 |
| AC-SEC-006 | `backend/backend/tests/test_security_settings.py`、`docs/ops/deployment.md` | 自动化/人工 |
| AC-OPS-001 | `core/tests/test_admin_status.py` | 自动化 |
| AC-OPS-002 | `core/tests/test_admin_status.py`、`test_dataset_models.py` | 自动化 |
| AC-OPS-003 | `core/tests/test_publication.py`、模块命令测试 | 自动化 |
| AC-OPS-004 | admin/status 测试与 `docs/ops/deployment.md` | 自动化/人工 |
| AC-OPS-005 | `docs/ops/deployment.md`、仓库任务审查 | 人工（无自动化任务） |
| AC-OPS-006 | `core/tests/test_locking.py`（死持有者立即回收 / 活持有者永不回收 / 跨主机按阈值 / 损坏锁按阈值 / 阈值 0 只允许死持有者 / 释放不删他人重建的锁） | 自动化 |

## 待所有者提供环境后执行的受控运行时验收

以下检查没有在 2026-09-09 自行执行：需要所有者提供已部署 HTTPS 服务地址、测试账号，并明确允许访问该环境。

1. 未登录访问业务页和 `/api/<app>/`，确认跳转/`401`，且不触发业务数据请求。
2. 登录后确认默认打开“板块资金流 → 开盘啦”，四个一级 Tab、键盘导航、窄屏横向滚动及状态提示均可用，且页面不出现数据源切换控件。
3. 在 Django admin 中以普通用户和 staff 用户分别验证权限与状态展示。
4. 使用真实可用缓存/旧快照验证 stale、partial、`DATA_PREPARING` 以及模块间隔离。
5. 由所有者决定是否允许开盘啦的受控上游 dry-run；上游被屏蔽时只验证预期失败语义，不绕过限制、不重试规避。
6. 验证 HTTPS、域名白名单、CSRF 可信来源、Django admin 静态文件和反向代理路由。

完成上述检查后，应在本文件补充服务地址（如可公开）、执行时间、操作者、使用的非敏感测试账号标识和结果，而不是把凭据写入仓库。
