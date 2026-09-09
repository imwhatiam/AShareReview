# 规格验收追踪矩阵

- **规格来源：** `docs/specs/a-share-market-review-integration-spec.md`
- **基准日期：** 2026-09-09
- **标准数量：** 102（含后续增加的 `AC-FLOW-008a`；早期任务描述中的“95 条”已过时）
- **证据状态含义：** “自动化”表示已有仓库测试或静态检查；“人工待执行”表示必须在所有者提供的已部署 HTTPS 环境中执行，当前没有声称已完成。

## 已运行的回归证据（2026-09-09）

| 验证 | 结果 |
| --- | --- |
| `python manage.py test backend.tests.test_module_isolation backend.tests.test_security_settings backend.tests.test_source_policy` | 14 tests passed |
| `./scripts/check_module_matrix.sh` | 五种 `core + 单业务 App` 配置的 check、迁移计划、命令/URL 发现及单 App 测试通过；未请求真实上游 |
| `python manage.py check` 与 `python manage.py makemigrations --check --dry-run` | 均通过；没有待生成迁移 |
| `python manage.py test` | 234 tests passed |
| 前端 `npm test -- --run`、`npm run lint`、`npm run build` | 49 tests、lint、build 全部通过；构建仅产生 ECharts 体积提示，不阻断构建 |
| 开盘啦受控真实上游验证（携带当前 `.env` 三项 KPL 配置 / 显式省略三个字段） | 两种模式均可完成资金流完整分页及父行业→子行业→股票列表链路；股票列表使用已发布的 2026-09-08 快照。2026-09-09 盘中当日股票列表的不可用与认证无关。 |
| `python manage.py test core.tests.test_kaipanla_industry_adapter kaipanla.tests.test_fetcher backend.tests.test_security_settings` | 16 tests passed；覆盖三类 KPL 字段为空时省略、非空时携带的契约。 |

真实网页/API、真实上游采集及部署环境验收仍未执行，原因和后续步骤见下文“待所有者提供环境后执行的受控运行时验收”。

## 自动化/人工证据映射

| 验收标准 | 证据 | 状态 |
| --- | --- | --- |
| AC-UI-001 | `frontend/src/app/AppShell.test.jsx`（匿名态不请求业务数据） | 自动化 |
| AC-UI-002 | `frontend/src/app/AppShell.test.jsx`（登录后默认开盘啦） | 自动化；真实浏览器待执行 |
| AC-UI-003 | `frontend/src/app/AppShell.test.jsx` | 自动化 |
| AC-UI-004 | `frontend/src/app/AppShell.test.jsx` | 自动化 |
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
| AC-SRC-000 | `core/tests/test_hithink_adapter.py`、`backend/tests/test_source_policy.py` | 自动化 |
| AC-SRC-000A | `core/tests/test_hithink_adapter.py`、`test_sync_daily_prices_commands.py` | 自动化 |
| AC-SRC-000B | `core/tests/test_kaipanla_industry_adapter.py`、`test_sync_industries_commands.py`；2026-09-09 真实上游验证 | 自动化；真实上游已验证（股票列表使用 2026-09-08 已发布快照） |
| AC-SRC-001 | `backend/tests/test_source_policy.py` | 自动化 |
| AC-SRC-002 | `backend/tests/test_security_settings.py`、`.gitignore` | 自动化；人工代码审查 |
| AC-SRC-003 | `kaipanla/tests/test_fetcher.py`、`core/tests/test_kaipanla_industry_adapter.py`、`backend/tests/test_security_settings.py`；2026-09-09 真实上游验证 | 自动化；真实上游已验证 |
| AC-SRC-004 | `eastmoney/tests/test_fetcher.py`、`eastmoney/tests/test_command.py` | 自动化 |
| AC-SRC-005 | `core/tests/test_management_contract.py`、日志脱敏相关测试 | 自动化 |
| AC-SRC-006 | `core/tests/test_hithink_adapter.py`、资金流 fetcher 测试 | 自动化 |
| AC-FLOW-001 | `kaipanla/tests/test_api.py`、`eastmoney/tests/test_api.py` | 自动化 |
| AC-FLOW-002 | `kaipanla/tests/test_api.py`、`eastmoney/tests/test_api.py` | 自动化 |
| AC-FLOW-003 | `kaipanla/tests/test_api.py`、`eastmoney/tests/test_api.py` | 自动化 |
| AC-FLOW-004 | `kaipanla/tests/test_queries.py`、`eastmoney/tests/test_queries.py` | 自动化 |
| AC-FLOW-005 | `kaipanla/tests/test_queries.py`、`eastmoney/tests/test_queries.py` | 自动化 |
| AC-FLOW-006 | `kaipanla/tests/test_publication.py`、`test_command.py` | 自动化 |
| AC-FLOW-007 | `eastmoney/tests/test_publication.py`、`test_api.py` | 自动化 |
| AC-FLOW-008 | `eastmoney/tests/test_fallback.py`、`test_command.py` | 自动化 |
| AC-FLOW-008a | `eastmoney/tests/test_fetcher.py`、`test_fallback.py`、`test_command.py` | 自动化; 真实上游屏蔽待环境观察 |
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
| AC-MOM-001 | `sector_momentum/tests/test_analysis.py` | 自动化 |
| AC-MOM-002 | `sector_momentum/tests/test_analysis.py` | 自动化 |
| AC-MOM-003 | `sector_momentum/tests/test_analysis.py` | 自动化 |
| AC-MOM-004 | `sector_momentum/tests/test_analysis.py` | 自动化 |
| AC-MOM-005 | `sector_momentum/tests/test_analysis.py`、`test_api.py` | 自动化 |
| AC-MOM-006 | `sector_momentum/tests/test_analysis.py` | 自动化 |
| AC-MOM-007 | `sector_momentum/tests/test_command.py`、`test_models.py` | 自动化 |
| AC-MOM-008 | `sector_momentum/tests/test_analysis.py`、前端页面测试 | 自动化 |
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
| AC-FALL-001 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-002 | `core/tests/test_file_cache.py`、各模块 fallback 测试 | 自动化 |
| AC-FALL-003 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-004 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-005 | `core/tests/test_locking.py`、fallback 测试 | 自动化 |
| AC-FALL-006 | 各模块 `test_fallback.py` | 自动化 |
| AC-FALL-007 | 同步、发布和 fallback 测试 | 自动化 |
| AC-FALL-008 | `core/tests/test_publication.py`、模块发布测试 | 自动化 |
| AC-FALL-009 | `core/tests/test_locking.py` | 自动化 |
| AC-TIME-001 | `core/tests/test_market_data_services.py`、模块命令测试 | 自动化 |
| AC-TIME-002 | `core/tests/test_market_data_services.py` | 自动化 |
| AC-TIME-003 | `core/tests/test_market_data_services.py` | 自动化 |
| AC-TIME-004 | `core/tests/test_market_data_services.py`、模块 fallback 测试 | 自动化 |
| AC-TIME-005 | `core/tests/test_market_data_services.py` | 自动化 |
| AC-API-001 | `backend/tests/test_module_isolation.py`、模块 API 测试 | 自动化 |
| AC-API-002 | `core/tests/test_api_contract.py`、模块 API 测试 | 自动化 |
| AC-API-003 | `core/tests/test_api_contract.py`、模块 API 测试 | 自动化 |
| AC-API-004 | `core/tests/test_session_api.py`、模块 API 测试 | 自动化 |
| AC-API-005 | `core/tests/test_api_contract.py`、模块 fallback 测试 | 自动化 |
| AC-API-006 | 模块 fallback/API 测试 | 自动化 |
| AC-API-007 | 模块 API 测试 | 自动化 |
| AC-API-008 | `scripts/check_module_matrix.sh` | 自动化 |
| AC-SEC-001 | `backend/tests/test_security_settings.py` | 自动化 |
| AC-SEC-002 | `core/tests/test_session_api.py` | 自动化 |
| AC-SEC-003 | `core/tests/test_admin_status.py`、Django admin 默认权限 | 自动化；真实反向代理待执行 |
| AC-SEC-004 | `backend/tests/test_security_settings.py`、`.gitignore`、发布前人工检查 | 自动化/人工 |
| AC-SEC-005 | `core/tests/test_api_contract.py`、模块 API 参数测试、React 默认转义 | 自动化 |
| AC-SEC-006 | `backend/tests/test_security_settings.py`、`docs/deployment.md` | 自动化/人工 |
| AC-OPS-001 | `core/tests/test_admin_status.py` | 自动化 |
| AC-OPS-002 | `core/tests/test_admin_status.py`、`test_dataset_models.py` | 自动化 |
| AC-OPS-003 | `core/tests/test_publication.py`、模块命令测试 | 自动化 |
| AC-OPS-004 | admin/status 测试与 `docs/deployment.md` | 自动化/人工 |
| AC-OPS-005 | `docs/deployment.md`、仓库任务审查 | 人工（无自动化任务） |

## 待所有者提供环境后执行的受控运行时验收

以下检查没有在 2026-09-09 自行执行：需要所有者提供已部署 HTTPS 服务地址、测试账号，并明确允许访问该环境。

1. 未登录访问业务页和 `/api/<app>/`，确认跳转/`401`，且不触发业务数据请求。
2. 登录后确认默认打开“板块资金流 → 开盘啦”，四个一级 Tab、两个资金流子 Tab、键盘导航、窄屏横向滚动及状态提示均可用。
3. 在 Django admin 中以普通用户和 staff 用户分别验证权限与状态展示。
4. 使用真实可用缓存/旧快照验证 stale、partial、`DATA_PREPARING`、东方财富无历史数据空页以及模块间隔离。
5. 由所有者决定是否允许东方财富与开盘啦的受控上游 dry-run；东方财富被屏蔽时只验证预期失败语义，不绕过限制、不重试规避。
6. 验证 HTTPS、域名白名单、CSRF 可信来源、Django admin 静态文件和反向代理路由。

完成上述检查后，应在本文件补充服务地址（如可公开）、执行时间、操作者、使用的非敏感测试账号标识和结果，而不是把凭据写入仓库。
