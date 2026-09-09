# A 股市场复盘系统整合任务清单

**状态：** 已批准；T01 的 REST 与开盘啦行业链路验证完成，后续实现可按依赖顺序恢复。
**规格：** `docs/specs/a-share-market-review-integration-spec.md`  
**计划说明：** `tasks/plan.md`

> 规则：按依赖顺序执行；每次只完成一个任务；不得顺带实现后续任务。文件范围是预计主要修改范围，若实际需要超过 5 个主要文件，先拆分并重新批准任务边界。所有真实网页或 Web API 测试执行前，必须先询问用户是否已有可用服务及地址。

## 阶段 A：外部可行性与项目底座

### T01：验证同花顺 REST 与开盘啦行业链路能力

- [x] **修改文件范围：** `docs/integrations/hithink-rest-and-kaipanla-capability.md`（只读验证且不得记录凭据）。
- **具体结果：** 记录已批准的同花顺 REST 端点、`X-api-key` 鉴权、股票/交易日历/日线字段、最近一年逐股票前复权参数，以及开盘啦父行业→子行业→股票链路和行业快照四字段约束；记录 API Key 实测最小权限与未知的 QPS/并发/日额度风险。
- **测试方式：** 对照公开文档逐项核验；在用户现有凭据环境中执行最小只读 REST 与开盘啦调用；敏感值只记录“可用/不可用”，不写入文档或日志。
- **验收标准：** ① 文档记录股票列表、交易日历、单股票最近一年 `interval=1d`/`adjust=forward` 日线及开盘啦父→子→股票链路的成功证据；② 记录多行业归属；③ 未公开额度明确转化为低频、有限退避和旧版本保留的实现约束。
- **潜在风险：** 文档能力与账号实际权限不一致；测试调用消耗额度；上游接口字段或限流策略变化。
- **依赖：** 无。
- **规模：** S（1~2 个文件）。

### T02：建立依赖、环境变量和仓库卫生基线

- [x] **修改文件范围：** `backend/requirements.txt`、`frontend/package.json`、`frontend/package-lock.json`、`.env.example`、`.gitignore`。
- **具体结果：** 锁定后端与前端依赖；登记六个数据库、缓存、安全、模块开关、同花顺、开盘啦、东方财富和轻量修复预算配置；忽略所有 SQLite、缓存、日志、构建产物和虚拟环境。
- **测试方式：** 创建无真实凭据的测试环境执行依赖安装检查；扫描 `.env.example` 只有占位符；运行 `git check-ignore` 验证数据库和缓存样例路径。
- **验收标准：** ① 所有规格 5.10 配置都有安全占位符；② 不硬编码真实 URL 参数以外的秘密值；③ `npm` 和 Python 依赖可重复安装。
- **潜在风险：** 同花顺 REST API 依赖未在 T01 确认前无法锁版；Django 6.1 与第三方包兼容性可能要求调整版本。
- **依赖：** T01（REST 数据源结论）。
- **规模：** M（5 个文件）。

### T03：配置六库布局和通用数据库路由

- [x] **修改文件范围：** `backend/backend/settings.py`、`backend/backend/db_router.py`、`backend/backend/env.py`、`backend/backend/tests/test_database_routing.py`。
- **具体结果：** 从根 `.env` 读取配置；将 `default` 指向 `core.sqlite3`；为五个业务 App 配置独立 SQLite；路由按 `app_label` 限制读写和迁移，禁止跨库关系。
- **测试方式：** 使用临时数据库路径运行路由单测；验证每个模型标签只允许迁移到自己的库；验证跨业务库关系返回禁止。
- **验收标准：** ① 六个文件路径均来自环境；② 业务 App 不能读写其他业务库；③ Django 认证与 Session 只落到 `default/core` 库。
- **潜在风险：** Django `default` 数据库不可省略；迁移路由配置错误可能造成表落错库或测试库冲突。
- **依赖：** T02。
- **规模：** M（4 个文件）。

## 检查点 A1（T01~T03）

- [x] 同花顺 REST 与开盘啦链路可行性结论已记录，无未处理的阻断项。
- [x] 数据库路由聚焦测试通过，配置中无真实凭据。
- [ ] 未创建任何业务模型或功能实现。

### T04：建立 `core` App 与根 API 骨架

- [x] **修改文件范围：** `backend/core/apps.py`、`backend/core/urls.py`、`backend/core/tests/test_app_bootstrap.py`、`backend/backend/settings.py`、`backend/backend/urls.py`。
- **具体结果：** 创建不可删除的 `core` App；挂载 `/api/core/`；保留 `/admin/`；项目可在尚无业务 App 时启动和检查。
- **测试方式：** 运行 `python manage.py check` 和 URL 解析测试；确认未知 `/api/...` 返回 404。
- **验收标准：** ① `core` 始终安装；② 根 URL 不直接导入未来业务视图；③ 基础检查通过。
- **潜在风险：** 过早把业务逻辑放入根 URL；测试导入尚未创建的模块。
- **依赖：** T03。
- **规模：** M（5 个文件）。

### T05：建立静态模块注册和启用装配

- [ ] **修改文件范围：** `backend/core/module_registry.py`、`backend/backend/settings.py`、`backend/backend/urls.py`、`backend/core/tests/test_module_registry.py`、`.env.example`。
- **具体结果：** 定义五个模块的 ID、名称、路由、API 前缀、导航组和顺序；由环境开关决定 App 安装与 URL 挂载；默认入口优先 `kaipanla`，禁用后顺延。
- **测试方式：** 在不同开关组合下重载设置/URL 配置，验证启用模块挂载、禁用模块不导入且 URL 不可解析。
- **验收标准：** ① 注册表字段满足 `/api/core/modules/` 契约；② 禁用模块不是仅隐藏而是完全不挂载；③ 全部禁用时 `core` 仍可检查。
- **潜在风险：** Python 导入缓存使开关测试产生假阳性；静态注册表与前端注册未来发生漂移。
- **依赖：** T04。
- **规模：** M（5 个文件）。

## 检查点 A2（T04~T05）

- [x] `core` 单独安装时 `python manage.py check` 通过。
- [ ] 五种开关组合的 URL 装配测试通过。
- [ ] 评审确认静态模块机制没有演变为在线插件系统。

## 阶段 B：`core` 公共契约

### T06：建立股票、交易日历和开盘啦父/子行业模型

- [x] **修改文件范围：** `backend/core/models/market.py`、`backend/core/models/__init__.py`、`backend/core/migrations/0001_market_reference.py`、`backend/core/tests/test_market_models.py`。
- **具体结果：** 建立股票基础信息、交易日历和当前开盘啦行业—股票快照；统一标准股票代码。行业快照只含 `industry_code`、`industry_name`、`industry_level` 和 `stock_codes` 四个业务字段，不保留历史有效期；父、子行业均入库，父行业股票列表由下属子行业股票去重汇总，子行业只保存不对外展示；同一股票允许出现在多个父行业的股票列表中。
- **测试方式：** 模型约束测试覆盖唯一键、交易所枚举、`parent`/`child` 行业标记、四字段快照和无历史有效期字段；覆盖同一股票出现在多个行业记录。
- **验收标准：** ① 满足 AC-CORE-004/005/006；② 不存在跨数据库外键；③ 北交所可被正确标识而非深证。
- **潜在风险：** 同花顺代码格式和交易所字段语义尚未完全确认；开盘啦响应结构或父/子行业分页规则变化。
- **依赖：** T03、T04、T01。
- **规模：** M（4 个文件）。

### T07：建立公共日行情、数据版本和运行状态模型

- [x] **修改文件范围：** `backend/core/models/datasets.py`、`backend/core/models/__init__.py`、`backend/core/migrations/0002_datasets.py`、`backend/core/tests/test_dataset_models.py`。
- **具体结果：** 建立前复权日行情唯一键、公共数据版本/完整性记录、模块运行状态摘要；状态使用稳定 `module_id` 字符串而不导入业务模型。
- **测试方式：** 测试股票+日期唯一约束、版本状态枚举、预期/实际/缺失计数和已删除模块字符串记录可保存。
- **验收标准：** ① 满足 AC-CORE-002/007/008；② `complete`、`partial`、`failed` 可区分；③ 状态模型不依赖业务 App。
- **潜在风险：** 日行情数据量使索引设计不足；版本字段若过度自由会削弱缓存一致性。
- **依赖：** T06。
- **规模：** M（4 个文件）。

### T08：建立公共查询与 15:00 日期服务

- [x] **修改文件范围：** `backend/core/services/calendar.py`、`backend/core/services/market_data.py`、`backend/core/services/contracts.py`、`backend/core/tests/test_market_data_services.py`。
- **具体结果：** 为业务 App 提供稳定的交易日窗口、最新完整业务日、公共行情/股票/行业映射只读查询和依赖版本对象；统一 Asia/Shanghai 与 15:00 资格判断。
- **测试方式：** 冻结时间测试 14:59:59、15:00:00、周末、休市日、缺日历、数据不完整和北京证券交易所情形。
- **验收标准：** ① 满足 AC-TIME-001~005；② 业务 App 无需自建节假日算法；③ 查询返回数据与版本，不暴露 ORM 模型给业务模块长期耦合。
- **潜在风险：** “15:00 有资格”被错误实现为“15:00 必然完整”；大查询可能一次加载过多行情。
- **依赖：** T06、T07。
- **规模：** M（4 个文件）。

## 检查点 B1（T06~T08）

- [ ] `core` 模型迁移在 `default/core` 库成功，其他库无这些表。
- [ ] 时间边界和公共查询测试通过。
- [ ] 模型没有历史行业有效期或跨库外键。

### T09：建立版本发布、互斥锁和运行状态服务

- [x] **修改文件范围：** `backend/core/services/publication.py`、`backend/core/services/locking.py`、`backend/core/services/run_status.py`、`backend/core/tests/test_publication.py`、`backend/core/tests/test_locking.py`。
- **具体结果：** 提供“开始运行—事务写入—完整性检查—发布版本—成功/失败收尾”的公共协调能力；同数据集并发互斥；失败保留最近成功版本并累计失败次数。
- **测试方式：** 注入写入异常、完整性失败和并发锁竞争，验证新版本不发布、旧版本仍可查、失败计数递增且成功后清零。
- **验收标准：** ① 满足 AC-OPS-002/003、AC-FALL-007/008/009；② 不跨远程请求持有数据库事务；③ 日志上下文含模块、数据集、日期和批次 ID。
- **潜在风险：** 文件锁在多进程/容器环境语义不同；事务与五个数据库别名组合复杂。
- **依赖：** T07。
- **规模：** M（5 个文件）。

### T10：建立版本化文件缓存工具

- [x] **修改文件范围：** `backend/core/services/file_cache.py`、`backend/core/services/cache_keys.py`、`backend/core/tests/test_file_cache.py`、`.env.example`。
- **具体结果：** 实现按模块/端点/参数摘要/数据版本隔离的 JSON 文件缓存；支持 TTL、大小限制、原子写、损坏回退和模块命名空间失效。
- **测试方式：** 临时目录测试命中、过期、损坏、版本不匹配、不可写目录、原子替换和跨模块隔离。
- **验收标准：** ① 满足 AC-FALL-001~004；② 缓存损坏不返回 500；③ 一个业务 App 不能失效另一个 App 的缓存。
- **潜在风险：** 参数摘要不稳定导致命中率低；并发写产生半文件；缓存内容意外包含敏感上游正文。
- **依赖：** T02、T09。
- **规模：** M（4 个文件）。

### T11：建立统一 API 外壳、错误码和参数校验

- [x] **修改文件范围：** `backend/core/api/responses.py`、`backend/core/api/errors.py`、`backend/core/api/validators.py`、`backend/core/tests/test_api_contract.py`。
- **具体结果：** 提供统一响应外壳、稳定错误映射、ISO 日期/天数/排行范围校验和 `business_date` 一致性检查。
- **测试方式：** 覆盖 200/202/400/401/403/404/409/503，恶意日期、超大整数、未知枚举和脚本字符串。
- **验收标准：** ① 满足 AC-API-002~007；② 无效参数不静默回退；③ 错误消息不包含内部异常或秘密值。
- **潜在风险：** 把所有模块正文强行统一；HTTP 状态与业务 `status` 混淆。
- **依赖：** T08。
- **规模：** M（4 个文件）。

## 检查点 B2（T09~T11）

- [ ] 发布、锁、缓存和 API 契约聚焦测试通过。
- [ ] 模拟失败后旧版本仍可读，缓存未被提前失效。
- [ ] 统一工具不包含任何具体业务算法。

### T12：建立 Session、健康检查和模块列表 API

- [x] **修改文件范围：** `backend/core/views.py`、`backend/core/urls.py`、`backend/core/tests/test_session_api.py`、`backend/core/tests/test_modules_api.py`、`backend/backend/settings.py`。
- **具体结果：** 实现 session 查询、登录、注销、模块列表和轻量健康检查；业务 API 统一要求登录；不提供注册接口。
- **测试方式：** DRF 客户端测试有效/无效登录、CSRF、Session 过期、普通用户、staff 用户、模块开关和健康检查无上游访问。
- **验收标准：** ① 满足 AC-API-004/008、AC-SEC-002/003；② 登录失败不可枚举账号；③ 模块列表只返回已启用项。
- **潜在风险：** 测试客户端默认绕过 CSRF；健康检查误做重量级依赖检查。
- **依赖：** T05、T11。
- **规模：** M（5 个文件）。

### T13：建立 Django 管理后台状态中心

- [x] **修改文件范围：** `backend/core/admin.py`、`backend/core/services/status_summary.py`、`backend/core/tests/test_admin_status.py`。
- **具体结果：** 在 Django admin 展示公共数据和五个模块的最新业务日期、成功时间、运行状态、完整性、版本、旧数据标志、失败次数与安全错误摘要；历史模块字符串不触发导入。
- **测试方式：** admin 页面权限测试、已删除/禁用模块状态渲染测试、错误摘要脱敏测试。
- **验收标准：** ① 满足 AC-OPS-001~005；② 非 staff 无法查看；③ 后台不提供启动/停止/重跑按钮和外部通知。
- **潜在风险：** admin 列表触发 N+1 查询；错误摘要保存敏感上游正文。
- **依赖：** T07、T09、T12。
- **规模：** M（3 个文件）。

## 检查点 B3（T12~T13）

- [x] Session、CSRF、模块列表和 admin 权限测试通过。
- [ ] 未登录业务访问返回 `401 AUTH_REQUIRED`。（待第一个业务 API 在 T23 实现后验证）
- [x] `core` 至此可独立运行且不导入业务模块。

## 阶段 C：同花顺公共数据链路

### T14：实现同花顺 REST API 适配边界

- [x] **修改文件范围：** `backend/core/integrations/hithink/client.py`、`backend/core/integrations/hithink/contracts.py`、`backend/core/integrations/hithink/mappers.py`、`backend/core/tests/test_hithink_adapter.py`、`backend/requirements.txt`。
- **具体结果：** 用单一 REST 适配层封装 T01 已确认的股票列表、交易日历和单股票历史日线端点；将 REST 字段映射为内部股票、日行情和日历契约。业务服务不接触上游字段名；行业—股票关系不经此适配层获取。
- **测试方式：** 使用假的 REST 传输覆盖正常、缺字段、类型错误、限流、权限不足和超时；静态扫描保证同花顺个股端点只在 `core` 的受控适配层调用。
- **验收标准：** ① 满足 AC-SRC-000/000A/001/002/005/006；② 所有凭据、端点、超时与限流设置来自环境；③ 业务 App 不存在同花顺 REST 调用或未批准数据源回退。
- **潜在风险：** REST 响应字段、分页语义或复权标志映射错误；上游限流、认证或权限策略变化。
- **依赖：** T01、T02、T06。
- **规模：** M（5 个文件）。

### T15：实现股票基础信息和交易日历同步

- [x] **修改文件范围：** `backend/core/services/sync_reference.py`、`backend/core/management/commands/sync_stock_master.py`、`backend/core/management/commands/sync_trading_calendar.py`、`backend/core/tests/test_sync_reference_commands.py`。
- **具体结果：** 两个独立命令通过同花顺 REST 同步股票清单和最近一年交易日历，支持日期参数、dry-run、版本记录、事务发布和非零失败退出。
- **测试方式：** 模拟 REST 数据运行命令测试，覆盖重复代码、空响应、日历缺口、dry-run 不写库和失败保留旧版本。
- **验收标准：** ① 股票代码和交易所标准化；② 交易日历成为唯一日期来源；③ 命令失败不覆盖最近成功版本。
- **潜在风险：** 退市/暂停上市的有效状态定义不清；REST 日历范围或字段语义与预期不一致。
- **依赖：** T09、T14。
- **规模：** M（4 个文件）。

### T16：实现开盘啦父/子行业和股票行业映射同步

- [x] **修改文件范围：** `backend/core/integrations/kaipanla/client.py`、`backend/core/services/sync_industries.py`、`backend/core/management/commands/sync_kaipanla_industry_snapshot.py`、`backend/core/tests/test_kaipanla_industry_adapter.py`、`backend/core/tests/test_sync_industries_commands.py`、`.env.example`。
- **具体结果：** 按开盘啦父行业→子行业→股票列表链路同步当前扁平行业快照；每行仅保存 `industry_code`、`industry_name`、`industry_level` 和 JSON `stock_codes`，采用整批替换/发布语义，不保留历史有效期。
- **测试方式：** 覆盖父子层级、父行业按子行业成分股去重汇总、父行业无子行业回退、同一股票属于多个父行业、缺成分、分页、dry-run 和中途失败；确认链路响应不完整时命令失败。
- **验收标准：** ① 满足 AC-CORE-005/006；② 只按开盘啦实际响应标注 `parent`/`child`，父行业的股票列表由子行业成分股去重汇总；③ 映射版本可供派生模块引用，当前派生模块只读取父行业。
- **潜在风险：** 开盘啦响应未显式区分层级或分页语义变化；多行业归属导致下游聚合重复计数时实现错误。
- **依赖：** T09、T14、T15。
- **规模：** M（4 个文件）。

## 检查点 C1（T14~T16）

- [x] 同花顺 REST 适配测试不发真实网络请求，字段与单位有文档证据。
- [x] 股票、日历、开盘啦父/子行业和映射命令 dry-run 测试通过。
- [x] 开盘啦父行业→子行业→股票链路已于 2026-09-08 验证可用；适配器契约测试覆盖其分页与失败语义。

### T17：实现首次最近一年初始化与日常单日行情同步

- [x] **修改文件范围：** `backend/core/services/sync_daily_prices.py`、`backend/core/management/commands/sync_stock_daily_prices.py`、`backend/core/management/commands/init_stock_daily_prices.py`、`backend/core/tests/test_sync_daily_prices_commands.py`、`backend/core/tests/fixtures/hithink_daily_prices.json`。
- **具体结果：** 提供两个边界明确的流程：`init_stock_daily_prices --years 1` 仅在首次部署且公共日行情为空时手动执行一次，以执行日为终点初始化滚动最近一年；`sync_stock_daily_prices --date YYYY-MM-DD` 供日常 crontab 使用，只同步该日且重复执行幂等。两者完成去重、有效交易标识、完整性统计和版本发布；Web API 不得触发初始化或全量同步。
- **测试方式：** 覆盖首次初始化最近一年边界、初始化只能显式调用、日常单日同步幂等、重复股票日期、缺失股票、停牌、空日、REST 逐股票请求、dry-run、中途失败和版本保留。
- **验收标准：** ① 满足 AC-CORE-001/002/007/008；② 不完整批次不发布 `complete`；③ `init_stock_daily_prices --years 1` 仅可作为首次一次性初始化，日常命令只处理一个交易日；④ 业务 App 无需复制原始日行情。
- **潜在风险：** 全市场一年逐股票 REST 请求超出未知额度或限流阈值；批次分页与额度控制错误；成交额单位不一致。
- **依赖：** T14、T15、T09。
- **规模：** M（5 个文件）。

### T18：固化公共命令的 dry-run、失败与日志契约

- [x] **修改文件范围：** `backend/core/management/base.py`、`backend/core/logging.py`、`backend/core/tests/test_management_contract.py`、`backend/backend/settings.py`。
- **具体结果：** 公共命令共享参数校验、dry-run、锁、批次上下文、耗时日志、敏感值遮蔽和非零退出行为；不把业务逻辑塞入基类。
- **测试方式：** 对 T15~T17 命令做参数化契约测试，检查 dry-run 零写入、并发锁、异常退出码和日志脱敏。
- **验收标准：** ① 所有公共命令满足规格 5.9；② 日志含定位字段但无 API Key/Token；③ 成功后失败次数清零。
- **潜在风险：** 基类抽象过度；捕获异常过宽掩盖编程错误。
- **依赖：** T15、T16、T17。
- **规模：** M（4 个文件）。

## 检查点 C2（T17~T18）

- [x] 公共数据全套命令测试通过，`makemigrations --check --dry-run` 无变化。
- [x] 最近一年限制、完整性和敏感日志测试通过。
- [x] 评审公共服务接口冻结后再开始五个业务模块。

## 阶段 D：开盘啦模块

### T19：建立 `kaipanla` 独立数据模型

- [x] **修改文件范围：** `backend/kaipanla/apps.py`、`backend/kaipanla/models.py`、`backend/kaipanla/migrations/0001_initial.py`、`backend/kaipanla/tests/test_models.py`、`backend/kaipanla/admin.py`。
- **具体结果：** 建立开盘啦板块资金流快照、分页/快照完整性和详细运行记录，全部路由到 `kaipanla.sqlite3`，不引用其他业务模型。
- **测试方式：** 模型唯一键、字段单位、时间对齐、完整性状态和数据库路由测试；在其他业务 App 禁用时迁移。
- **验收标准：** ① 满足 AC-MOD-003/007；② 保存规格 5.3.1 的上游实际字段；③ 必要分页缺失可被明确表示。
- **潜在风险：** 直接照搬旧模型会携带旧缓存或日历耦合；上游数值单位需要保持一致。
- **依赖：** T05、T09。
- **规模：** M（5 个文件）。

### T20：迁移开盘啦请求、解析和分页采集

- [x] **修改文件范围：** `backend/kaipanla/services/client.py`、`backend/kaipanla/services/parser.py`、`backend/kaipanla/services/fetcher.py`、`backend/kaipanla/tests/test_fetcher.py`、`.env.example`。
- **具体结果：** 使用批准的 POST URL、表单参数、80 条分页、DeviceID 和可选用户凭据；保留响应日期/时间语义，所有可变值来自环境。
- **测试方式：** 模拟多页、重复板块、空页、乱码/非法 JSON、超时、有限重试和某必要页失败。
- **验收标准：** ① 满足 AC-SRC-003/005/006；② 任一必要分页失败时结果不可标为完整；③ 不引入 BlueStacks、ADB、抓包流程。
- **潜在风险：** 开盘啦响应结构漂移；时间戳与业务日期不一致；旧代码中的隐式默认参数被遗漏。
- **依赖：** T02、T19。
- **规模：** M（5 个文件）。

### T21：实现开盘啦快照发布管理命令

- [x] **修改文件范围：** `backend/kaipanla/services/writer.py`、`backend/kaipanla/management/commands/fetch_kaipanla_sector_fund_flow.py`、`backend/kaipanla/tests/test_command.py`、`backend/kaipanla/tests/test_publication.py`。
- **具体结果：** 命令支持按公共交易日历判断的交易时段无参数模式、`--latest` 和 `--dry-run`；写入事务完成并通过分页完整性后才发布版本和失效本模块缓存。开盘啦资金流接口与东方财富资金流接口均未获得经实际请求验证的历史快照参数支持，因此当前不提供 `--date`、`--snapshot-time` 或其他显式历史时间参数。
- **测试方式：** 命令测试成功、必要页失败、数据库异常、锁冲突、dry-run、旧版本保留和非零退出码。
- **验收标准：** ① 满足 AC-FLOW-006、AC-FALL-007/008；② 失败不破坏最近快照；③ 只操作 `kaipanla` 数据库和缓存命名空间。
- **潜在风险：** 盘中重复运行造成重复快照；对齐时间错误导致同一槽位覆盖异常。
- **依赖：** T09、T10、T18、T20。
- **规模：** M（4 个文件）。

## 检查点 D1（T19~T21）

- [x] `kaipanla` 独立迁移、采集命令 dry-run 和失败发布测试通过。
- [x] 无任何 `eastmoney`、`stock_moves`、`sector_momentum`、`hundred_day` 导入。
- [ ] 上游参数与 `fundflow` 参考实现逐项对照完成。

### T22：实现开盘啦单日与多日查询服务

- [x] **修改文件范围：** `backend/kaipanla/services/queries.py`、`backend/kaipanla/services/intraday.py`、`backend/kaipanla/services/history.py`、`backend/kaipanla/tests/test_queries.py`。
- **具体结果：** 返回固定 5 分钟交易轴、流入/流出排行和板块序列；多日仅用交易日历与每日 15:00 快照，缺失日期形成警告而非伪造数据。
- **测试方式：** 覆盖 09:30~11:30/13:00~15:00、排行上限30、1/5/10/20日、休市日、缺15:00、稳定排序和空数据。
- **验收标准：** ① 满足 AC-FLOW-001~005；② 默认结果可支持前25展示、前5勾选；③ 不自行实现节假日日历。
- **潜在风险：** 旧项目“沿用前值”细节遗漏；正负方向排序和空值处理不一致。
- **依赖：** T08、T19、T21。
- **规模：** M（4 个文件）。

### T23：实现开盘啦 API、缓存与轻量修复

- [x] **修改文件范围：** `backend/kaipanla/views.py`、`backend/kaipanla/urls.py`、`backend/kaipanla/services/read_path.py`、`backend/kaipanla/tests/test_api.py`、`backend/kaipanla/tests/test_fallback.py`。
- **具体结果：** 提供 sectors、intraday、history、dates API；按缓存→数据库→一次有界远程修复读取；返回统一外壳、实际日期、版本、stale、partial/preparing 状态。远程修复仅限上海当日、单页、无重试、最多1,000行且超时不超过 `.env` 的硬上限；两个资金流命令均不提供未被上游验证支持的 `--snapshot-time`。
- **测试方式：** API 测试认证、参数边界、缓存命中、损坏回退、数据库命中、旧缓存、≤1000行修复、5秒硬超时和并发锁。
- **验收标准：** ① 满足 AC-API、AC-FALL、AC-FLOW 的开盘啦条目；② Web 请求不执行多日/全量采集；③ 禁用模块后 URL 不挂载。
- **潜在风险：** 远程修复在请求线程超预算；错误地把显式日期替换为最新日期。
- **依赖：** T10、T11、T12、T21、T22。
- **规模：** M（5 个文件）。

## 检查点 D2（T22~T23）

- [x] 开盘啦全部聚焦测试通过，API 契约与缓存顺序可证。
- [x] 15:00 缺失不会被其他时间冒充。
- [x] 单独启用 `core + kaipanla` 时检查和 URL 测试通过。

## 阶段 E：东方财富模块

### T24：建立 `eastmoney` 独立数据模型

- [x] **修改文件范围：** `backend/eastmoney/apps.py`、`backend/eastmoney/models.py`、`backend/eastmoney/migrations/0001_initial.py`、`backend/eastmoney/tests/test_models.py`、`backend/eastmoney/admin.py`。
- **具体结果：** 建立东方财富行业资金流快照、流入/流出方向状态、部分完整性和详细运行记录，全部路由到 `eastmoney.sqlite3`。
- **测试方式：** 模型唯一性、双榜状态、partial/complete 约束、字段单位和独立数据库迁移测试。
- **验收标准：** ① 可分别记录两侧成功状态；② 两侧都失败不能表示为已发布版本；③ 不引用 `kaipanla` 模型或服务。
- **潜在风险：** 旧 `fundflow` App 名称与新 `eastmoney` 重命名造成迁移引用遗漏。
- **依赖：** T05、T09。
- **规模：** M（5 个文件）。

### T25：迁移东方财富双榜请求和解析

- [x] **修改文件范围：** `backend/eastmoney/services/client.py`、`backend/eastmoney/services/parser.py`、`backend/eastmoney/services/fetcher.py`、`backend/eastmoney/tests/test_fetcher.py`、`.env.example`。
- **具体结果：** 使用批准的 GET URL、行业 `fs`、字段清单、流入/流出参数、等待和有限重试；两侧独立采集并合并重复代码。东方财富拒绝或屏蔽请求是可接受的上游不可用结果。
- **测试方式：** 模拟两侧成功、单侧失败、双侧失败、空榜、响应字段变化、限流、重试截止和重复行业覆盖。
- **验收标准：** ① 满足 AC-SRC-004~006；② 单侧失败保留另一侧；③ 双侧失败无可发布数据。
- **潜在风险：** 真实上游等待策略远超 Web 预算；字段 `f*` 语义变化不易察觉。
- **依赖：** T02、T24。
- **规模：** M（5 个文件）。

### T26：实现东方财富部分成功发布管理命令

- [x] **修改文件范围：** `backend/eastmoney/services/writer.py`、`backend/eastmoney/management/commands/fetch_eastmoney_sector_fund_flow.py`、`backend/eastmoney/tests/test_command.py`、`backend/eastmoney/tests/test_publication.py`。
- **具体结果：** 命令支持交易时段、`--latest` 和 dry-run；双侧成功发布 complete，单侧成功发布 partial，双侧失败（包括被上游屏蔽）只记录失败运行、不发布新版本、不失效缓存并保留旧快照，也不影响其他模块。资金流接口没有经验证的历史时间参数，因此不提供 `--date` 或 `--snapshot-time`。
- **测试方式：** 覆盖三种完整性、数据库异常、锁冲突、dry-run、缓存失效顺序、旧成功版本保留和退出码。
- **验收标准：** ① 满足 AC-FLOW-007/008；② partial 响应可定位缺失方向；③ 只操作 `eastmoney` 库和缓存。
- **潜在风险：** partial 版本被后续查询误当 complete；长等待使 crontab 重叠。
- **依赖：** T09、T10、T18、T25。
- **规模：** M（4 个文件）。

## 检查点 E1（T24~T26）

- [x] 东方财富模型、双榜和发布测试通过。
- [x] 单侧成功/双侧失败语义与规格一致。
- [x] 与开盘啦无 Python 或数据库依赖。

### T27：实现东方财富单日与多日查询服务

- [x] **修改文件范围：** `backend/eastmoney/services/queries.py`、`backend/eastmoney/services/intraday.py`、`backend/eastmoney/services/history.py`、`backend/eastmoney/tests/test_queries.py`。
- **具体结果：** 形成与开盘啦相同路径形状的固定交易轴、双方向序列和1/5/10/20日汇总，同时保留东方财富 partial 警告。
- **测试方式：** 覆盖双榜、单榜、空榜、排行0..30、缺15:00、多日交易窗口、稳定排序和字段空值。
- **验收标准：** ① 满足 AC-FLOW-001~005/007；② 不把 partial 改写成 complete；③ 多日只使用每日15:00快照。
- **潜在风险：** 为追求共享而与开盘啦形成业务耦合；单侧数据对方向排名造成误导。
- **依赖：** T08、T24、T26。
- **规模：** M（4 个文件）。

### T28：实现东方财富 API、缓存与兜底

- [x] **修改文件范围：** `backend/eastmoney/views.py`、`backend/eastmoney/urls.py`、`backend/eastmoney/services/read_path.py`、`backend/eastmoney/tests/test_api.py`、`backend/eastmoney/tests/test_fallback.py`。
- **具体结果：** 提供与开盘啦同形状 API；按缓存→数据库读取；因正常双榜采集超预算，Web 默认返回旧数据或 `202 DATA_PREPARING`，不执行长远程采集。上游屏蔽且没有旧数据时，前端允许显示空内容及数据不可用状态。
- **测试方式：** 覆盖认证、参数错误、partial、缓存损坏、数据库命中、旧缓存、无数据202、禁用404和不调用长采集器断言。
- **验收标准：** ① 满足 AC-API 与 AC-FALL；② Web 请求不会触发东方财富长等待双榜；③ 返回旧数据时 `stale=true` 且有警告。
- **潜在风险：** 错误复用开盘啦轻量修复逻辑；接口形状一致被误解为业务数据完全一致。
- **依赖：** T10、T11、T12、T26、T27。
- **规模：** M（5 个文件）。

## 检查点 E2（T27~T28）

- [x] 东方财富 API 和兜底测试通过。
- [x] 单独启用 `core + eastmoney` 时检查和 URL 测试通过。
- [x] Web 路径无长时间双榜远程调用。

## 阶段 F：三个盘后分析模块

### T29：建立 `stock_moves` 数据模型

- [x] **修改文件范围：** `backend/stock_moves/apps.py`、`backend/stock_moves/models.py`、`backend/stock_moves/migrations/0001_initial.py`、`backend/stock_moves/tests/test_models.py`、`backend/stock_moves/admin.py`。
- **具体结果：** 保存业务日期、公共行情版本、四组明细/排序、组计数、去重总数和运行记录；不复制公共日行情。
- **测试方式：** 测试分组枚举、唯一性、排序字段、版本引用字符串、独立数据库和无日行情复制表。
- **验收标准：** ① 满足规格 5.3.3；② 无跨库外键；③ 只依赖 `core` 的稳定代码/版本标识。
- **潜在风险：** 将行业名称快照保存与“复制公共事实”混淆；统计摘要与明细不一致。
- **依赖：** T05、T07、T08。
- **规模：** M（5 个文件）。

### T30：实现大涨跌幅与大成交量算法和命令

- [x] **修改文件范围：** `backend/stock_moves/services/analysis.py`、`backend/stock_moves/services/writer.py`、`backend/stock_moves/management/commands/build_stock_moves.py`、`backend/stock_moves/tests/test_analysis.py`、`backend/stock_moves/tests/test_command.py`。
- **具体结果：** 从 `core` 查询当日完整行情，按 ±8% 和8亿元阈值构建上证/深证四组；北交所排除出四组但形成警告；事务发布派生版本。
- **测试方式：** 合成样例覆盖等号边界、阈值任一不满足、排序、空组、去重计数、北交所、缺名称/行业、dry-run和源版本变化。
- **验收标准：** ① 满足 AC-MOVE-001~005/007/008；② 公共数据不完整时不发布；③ 命令只写 `stock_moves.sqlite3`。
- **潜在风险：** 成交额单位误判导致阈值扩大/缩小1万倍；涨跌幅字段与本地计算语义不一致。
- **依赖：** T18、T29。
- **规模：** M（5 个文件）。

### T31：实现 `stock_moves` API、缓存与本地修复

- [x] **修改文件范围：** `backend/stock_moves/views.py`、`backend/stock_moves/urls.py`、`backend/stock_moves/services/read_path.py`、`backend/stock_moves/tests/test_api.py`、`backend/stock_moves/tests/test_fallback.py`。
- **具体结果：** 提供结果和日期 API；缓存→数据库→预算内本地重算；需要远程全市场同步时返回旧数据或202；正文含四组、计数和去重代码。
- **测试方式：** 覆盖认证、显式日期、空组、旧版本、公共版本变化、本地重算、禁止远程全量同步和错误外壳。
- **验收标准：** ① 满足 AC-MOVE-005/007 与 AC-FALL；② API 不复制或修改算法；③ `business_date` 与明细日期一致。
- **潜在风险：** 请求内本地重算在数据量大时超过预算；日期列表误包含失败版本。
- **依赖：** T10、T11、T12、T30。
- **规模：** M（5 个文件）。

## 检查点 F1（T29~T31）

- [x] `stock_moves` 模型、算法、命令和 API 测试通过。
- [x] 等号阈值、北交所和空组回归已锁定。
- [x] 单独启用 `core + stock_moves` 时独立工作。

### T32：建立 `sector_momentum` 数据模型

- [x] **修改文件范围：** `backend/sector_momentum/apps.py`、`backend/sector_momentum/models.py`、`backend/sector_momentum/migrations/0001_initial.py`、`backend/sector_momentum/tests/test_models.py`、`backend/sector_momentum/admin.py`。
- **具体结果：** 保存两种分析口径、行业排名和评分构成、结构化股票明细、未映射数量、公共行情/行业映射版本和运行记录。
- **测试方式：** 模型约束测试两种口径、排名唯一性、版本字段、结构化明细和独立数据库。
- **验收标准：** ① 满足规格 5.3.4；② 不复制公共行情表；③ 未映射数量可被持久化。
- **潜在风险：** JSON 明细过大；聚合数值精度选择影响排序稳定性。
- **依赖：** T05、T07、T08。
- **规模：** M（5 个文件）。

### T33：实现板块动量算法和命令

- [x] **修改文件范围：** `backend/sector_momentum/services/analysis.py`、`backend/sector_momentum/services/writer.py`、`backend/sector_momentum/management/commands/build_sector_momentum.py`、`backend/sector_momentum/tests/test_analysis.py`、`backend/sector_momentum/tests/test_command.py`。
- **具体结果：** 计算“涨幅>5%”和“全市场涨幅前5%”两套开盘啦父行业前10；子行业仅入库，不生成当前分析结果；稳定截断；评分=`数量×平均涨幅×行业成交额占比`；记录未映射股票。
- **测试方式：** 覆盖恰好5%、样本最少1、floor边界、同涨幅稳定排序、全市场成交额、评分公式、未映射、空市场和dry-run。
- **验收标准：** ① 满足 AC-MOM-001~007；② 未映射股票进入全市场分母但不被错误分组；③ 公共版本变化使结果可识别为过期。
- **潜在风险：** 全市场有效股票定义错误；浮点舍入在排序前后顺序不一致。
- **依赖：** T18、T32。
- **规模：** M（5 个文件）。

### T34：实现 `sector_momentum` API、缓存与本地修复

- [x] **修改文件范围：** `backend/sector_momentum/views.py`、`backend/sector_momentum/urls.py`、`backend/sector_momentum/services/read_path.py`、`backend/sector_momentum/tests/test_api.py`、`backend/sector_momentum/tests/test_fallback.py`。
- **具体结果：** 提供结果和日期 API；返回全市场成交额、两套排行、评分构成、股票明细和未映射警告；支持预算内本地重算。
- **测试方式：** 覆盖认证、日期、缓存/数据库/本地计算来源、旧版本、202、未映射警告、空排行和恶意参数。
- **验收标准：** ① 满足 AC-MOM 与 AC-API；② 前端无需解析 Base64 图；③ 请求中不触发公共远程同步。
- **潜在风险：** 大量股票明细导致缓存项过大；旧派生版本 stale 判断遗漏行业映射版本。
- **依赖：** T10、T11、T12、T33。
- **规模：** M（5 个文件）。

## 检查点 F2（T32~T34）

- [x] 板块动量公式、边界样本和 API 测试通过。
- [x] 单独启用 `core + sector_momentum` 时独立工作。
- [x] 结果同时记录行情版本和行业映射版本。

### T35：建立 `hundred_day` 数据模型

- [x] **修改文件范围：** `backend/hundred_day/apps.py`、`backend/hundred_day/models.py`、`backend/hundred_day/migrations/0001_initial.py`、`backend/hundred_day/tests/test_models.py`、`backend/hundred_day/admin.py`。
- **具体结果：** 保存股票级新高/新低等价结果、行业聚合、每日趋势、有效股票数、行情版本、行业映射版本和运行记录。
- **测试方式：** 测试日期/股票唯一性、行业聚合类型、趋势分母空值、版本字段和独立数据库迁移。
- **验收标准：** ① 满足规格 5.3.5；② 可重建行业和趋势响应；③ 不保存公共收盘价复制表。
- **潜在风险：** 同时保存股票级与聚合结果增加一致性维护成本；JSON 与关系表取舍影响查询。
- **依赖：** T05、T07、T08。
- **规模：** M（5 个文件）。

### T36：固化百日新高新低股票级算法

- [x] **修改文件范围：** `backend/hundred_day/services/flags.py`、`backend/hundred_day/tests/test_flags.py`、`backend/hundred_day/tests/fixtures/hundred_day_regression.json`。
- **具体结果：** 严格实现前99个全市场交易日位置、`shift(1).rolling(99)`、历史缺失填0、目标日缺失不填；目标价等于极值也触发标志。
- **测试方式：** 回归样例覆盖第99/100个位置、新上市、历史停牌、目标日停牌、等于最大/最小、全0历史和历史不足。
- **验收标准：** ① 满足 AC-HD-001~005；② 历史不足返回明确状态而非全零；③ 不“修正”旧算法的填0口径。
- **潜在风险：** pandas 与纯 Python 窗口边界差一日；全0历史可能同时触发高低，需要按规格样例明确结果。
- **依赖：** T08、T35。
- **规模：** M（3 个文件）。

### T37：实现百日行业聚合、趋势和构建命令

- [x] **修改文件范围：** `backend/hundred_day/services/analysis.py`、`backend/hundred_day/services/writer.py`、`backend/hundred_day/management/commands/build_hundred_day.py`、`backend/hundred_day/tests/test_analysis.py`、`backend/hundred_day/tests/test_command.py`。
- **具体结果：** 聚合当前开盘啦父行业新高/新低及股票明细；子行业仅入库，不生成当前分析结果；生成最多100个交易日结构化比例趋势；计算输入最多199个交易日位置；事务发布结果。
- **测试方式：** 覆盖行业计数一致性、未映射、分母0返回空值、100日趋势截断、199日输入、历史不足、dry-run和源版本变化。
- **验收标准：** ① 满足 AC-HD-006~009；② 不生成必须依赖的 Base64 PNG；③ 公共历史不足时命令明确失败/不发布。
- **潜在风险：** 一年自然日不足以覆盖极端长假下199个交易日位置；一次加载全市场宽表的内存占用。
- **依赖：** T18、T36。
- **规模：** M（5 个文件）。

## 检查点 F3（T35~T37）

- [x] 百日股票级、行业级和趋势回归测试通过。
- [x] 99/100/199 日边界经人工复核。
- [x] 不存在服务端图像作为 API 必需契约。

### T38：实现 `hundred_day` API、缓存与本地修复

- [x] **修改文件范围：** `backend/hundred_day/views.py`、`backend/hundred_day/urls.py`、`backend/hundred_day/services/read_path.py`、`backend/hundred_day/tests/test_api.py`、`backend/hundred_day/tests/test_fallback.py`。
- **具体结果：** 提供结果和日期 API；返回总数、行业排行、股票明细、结构化趋势和不足历史错误；支持缓存→数据库→预算内本地重算。
- **测试方式：** 覆盖认证、日期、`INSUFFICIENT_HISTORY`、缓存损坏、旧版本、公共数据缺失、202和趋势结构。
- **验收标准：** ① 满足 AC-HD 与 AC-API；② 无历史时不伪造全零；③ 请求中不执行公共历史初始化或全量同步。
- **潜在风险：** 本地重算可能超过5秒，应基于预估直接返回202；趋势终点与页面日期不一致。
- **依赖：** T10、T11、T12、T37。
- **规模：** M（5 个文件）。

## 检查点 F4（T38）

- [x] 单独启用 `core + hundred_day` 时检查、迁移、命令 dry-run、测试和 URL 均通过。
- [x] 三个盘后模块均只读 `core` 公共契约，彼此无依赖。

## 阶段 G：统一前端

### T39：建立 React 工程、测试工具和 API 客户端

- [x] **修改文件范围：** `frontend/package.json`、`frontend/package-lock.json`、`frontend/vite.config.js`、`frontend/src/api/client.js`、`frontend/src/api/client.test.js`。
- **具体结果：** 建立 React/Vite 入口所需依赖、lint/build/test 命令和携带 Session/CSRF 的 API 客户端；统一解析响应外壳和401处理。
- **测试方式：** 客户端单测 200/202/401/partial/stale/error、请求取消和 CSRF；运行 lint、test、build。
- **验收标准：** ① 前端不硬编码生产服务地址；② 401 可触发统一登出流程；③ 各业务正文保持独立类型/解析。
- **潜在风险：** axios/fetch 选择与旧代码不一致；测试工具引入过多依赖。
- **依赖：** T02、T11、T12。
- **规模：** M（5 个文件）。

### T40：实现登录态、产品外壳和模块导航

- [x] **修改文件范围：** `frontend/src/App.jsx`、`frontend/src/app/AuthGate.jsx`、`frontend/src/app/LoginPage.jsx`、`frontend/src/app/moduleRegistry.js`、`frontend/src/app/AppShell.test.jsx`。
- **具体结果：** 未登录仅显示登录页；登录后根据后端启用模块生成四个一级 Tab 和板块资金流二级 Tab；默认开盘啦，禁用时顺延。
- **测试方式：** 组件测试未登录不请求业务数据、登录成功默认入口、Session 过期、单模块禁用、全部禁用和四个中文标签。
- **验收标准：** ① 满足 AC-UI-001~005；② 禁用入口不渲染；③ 登录失败为通用提示。
- **潜在风险：** 前后端静态注册漂移；把子模块开关错误映射为整个板块资金流一级 Tab。
- **依赖：** T05、T12、T39。
- **规模：** M（5 个文件）。

### T41：建立统一设计令牌和数据状态组件

- [x] **修改文件范围：** `frontend/src/styles/tokens.css`、`frontend/src/index.css`、`frontend/src/shared/DataState.jsx`、`frontend/src/shared/DataMeta.jsx`、`frontend/src/shared/DataState.test.jsx`。
- **具体结果：** 统一上涨红、下跌绿、中性/错误色、排版和间距；提供加载、空、过期、准备中、部分成功、失败状态及业务日期/版本展示。
- **测试方式：** 组件状态测试、颜色语义 DOM/CSS 检查、错误状态不复用涨跌色；运行前端构建。
- **验收标准：** ① 满足 AC-UI-007/008；② 所有模块可复用但组件不解释业务正文；③ stale/partial 警告始终可见。
- **潜在风险：** 中国市场红涨绿跌语义被通用组件反转；仅靠颜色表达状态影响可访问性。
- **依赖：** T39。
- **规模：** M（5 个文件）。

## 检查点 G1（T39~T41）

- [x] 前端 lint、test、build 通过。
- [x] 登录后默认路由和全部禁用情形测试通过。
- [ ] 状态组件文字和颜色语义经评审。

### T42：迁移板块资金流共享控件和图表

- [x] **修改文件范围：** `frontend/src/features/sector-flow/FlowControls.jsx`、`frontend/src/features/sector-flow/RankingList.jsx`、`frontend/src/features/sector-flow/IntradayChart.jsx`、`frontend/src/features/sector-flow/HistoryChart.jsx`、`frontend/src/features/sector-flow/flowView.test.jsx`。
- **具体结果：** 迁移日期/1、5、10、20日控件、双排行勾选、分时和多日图表；缺失点保持空值；共享组件通过属性接收模块数据，不直接调用具体 API。
- **测试方式：** 组件测试前25、默认前5、勾选切换、时间轴、历史窗口和缺失点不画0；构建检查 ECharts。
- **验收标准：** ① 保留 `fundflow` 核心交互；② 共享层无 `kaipanla`/`eastmoney` API 导入；③ 同交易日保留选择所需接口可用。
- **潜在风险：** 过度抽象掩盖两数据源 partial 差异；ECharts tooltip 使用未净化 HTML。
- **依赖：** T41。
- **规模：** M（5 个文件）。

### T43：接入开盘啦子 Tab

- [x] **修改文件范围：** `frontend/src/features/kaipanla/KaipanlaPage.jsx`、`frontend/src/features/kaipanla/useKaipanlaData.js`、`frontend/src/features/kaipanla/KaipanlaPage.test.jsx`、`frontend/src/app/moduleRegistry.js`。
- **具体结果：** 调用 `/api/kaipanla/` 系列接口，支持日期、当日/多日、排行选择、状态元数据；同一交易日保留选择，切换日期恢复默认前5。
- **测试方式：** 模拟 API 测试默认加载、日期切换、历史模式、选择保持/重置、stale、202、空数据和错误。
- **验收标准：** ① 满足 AC-FLOW-009；② 默认产品入口显示该页；③ 失败仅影响当前内容区。
- **潜在风险：** 旧请求晚返回覆盖新日期；前端默认请求25与后端上限30不一致。
- **依赖：** T23、T40、T42。
- **规模：** M（4 个文件）。

### T44：接入东方财富子 Tab

- [x] **修改文件范围：** `frontend/src/features/eastmoney/EastmoneyPage.jsx`、`frontend/src/features/eastmoney/useEastmoneyData.js`、`frontend/src/features/eastmoney/EastmoneyPage.test.jsx`、`frontend/src/app/moduleRegistry.js`。
- **具体结果：** 调用 `/api/eastmoney/` 系列接口并复用资金流控件；显式展示单侧失败、旧数据和准备中，不把 partial 当完整。
- **测试方式：** 模拟完整、流入缺失、流出缺失、双侧无数据、历史模式、日期切换和禁用模块。
- **验收标准：** ① 两个子 Tab 交互一致；② partial 明确指出缺失方向；③ 东方财富错误不影响开盘啦已加载状态。
- **潜在风险：** 复用 hook 导致两个 Tab 请求/状态串扰；隐藏 partial 警告。
- **依赖：** T28、T40、T42。
- **规模：** M（4 个文件）。

## 检查点 G2（T42~T44）

- [x] 两个板块资金流子 Tab 的组件测试与构建通过。
- [x] 默认开盘啦、同日选择保持、换日重置和 partial 展示通过。
- [x] 两数据源前端状态彼此隔离。

### T45：实现大涨跌幅与大成交量个股页面（仅父行业标签）

- [x] **修改文件范围：** `frontend/src/features/stock-moves/StockMovesPage.jsx`、`frontend/src/features/stock-moves/useStockMoves.js`、`frontend/src/features/stock-moves/StockGroupTable.jsx`、`frontend/src/features/stock-moves/StockMovesPage.test.jsx`。
- **具体结果：** 展示日期、四组统计和表格、总数与全部去重代码；支持复制全部并对复制失败给出可见提示。
- **测试方式：** 模拟四组、空组、北交所警告、stale/202、日期切换、剪贴板成功和失败。
- **验收标准：** ① 满足 AC-MOVE-006/007；② 空组不使整页失败；③ 复制内容与去重代码列表一致。
- **潜在风险：** 浏览器剪贴板权限差异；成交额单位展示与 API 单位重复换算。
- **依赖：** T31、T40、T41。
- **规模：** M（4 个文件）。

### T46：实现板块动量页面（仅父行业）

- [x] **修改文件范围：** `frontend/src/features/sector-momentum/SectorMomentumPage.jsx`、`frontend/src/features/sector-momentum/useSectorMomentum.js`、`frontend/src/features/sector-momentum/MomentumChart.jsx`、`frontend/src/features/sector-momentum/SectorMomentumPage.test.jsx`。
- **具体结果：** 分区展示两套前10行业、评分构成、图表和可展开股票明细；展示未映射数量警告。
- **测试方式：** 模拟两种口径、展开/收起、空排行、未映射、stale、日期切换和单模块失败。
- **验收标准：** ① 核心图表和明细功能不减少；② 评分三项可核对；③ 图表使用结构化 API 数据。
- **潜在风险：** 图表归一化方式改变用户理解；展开大量股票影响窄屏布局。
- **依赖：** T34、T40、T41。
- **规模：** M（4 个文件）。

### T47：实现百日新高新低占比页面（仅父行业）

- [x] **修改文件范围：** `frontend/src/features/hundred-day/HundredDayPage.jsx`、`frontend/src/features/hundred-day/useHundredDay.js`、`frontend/src/features/hundred-day/RatioTrendChart.jsx`、`frontend/src/features/hundred-day/HundredDayPage.test.jsx`。
- **具体结果：** 展示有效数、新高/新低数、行业排行、可展开股票和最多100日占比趋势；历史不足显示明确提示。
- **测试方式：** 模拟正常趋势、空行业、分母空值、历史不足、stale、日期切换和趋势终点一致性。
- **验收标准：** ① 满足 AC-HD-008；② 不依赖 Base64 图片；③ 缺失趋势点不画为0。
- **潜在风险：** 新低图表正负方向视觉与旧页面不同；百分比重复乘100。
- **依赖：** T38、T40、T41。
- **规模：** M（4 个文件）。

## 检查点 G3（T45~T47）

- [x] 三个盘后页面组件测试、lint 和 build 通过。
- [x] 四个一级 Tab 名称、顺序和核心功能经规格对照。
- [x] 图表均从结构化数据渲染，状态与警告可见。

### T48：完成前端竞态、剪贴板、窄屏和状态回归

- [x] **修改文件范围：** `frontend/src/app/AppShell.test.jsx`、`frontend/src/shared/DataState.test.jsx`、`frontend/src/features/integration.test.jsx`、`frontend/src/index.css`、`frontend/src/api/client.js`。
- **具体结果：** 统一取消过期请求/请求序号策略；验证单模块失败不清空导航；完善键盘可操作、非颜色提示和常用桌面/窄屏布局。
- **测试方式：** 人工控制 Promise 返回顺序测试竞态；剪贴板失败；Tab 键导航；组件级视口测试；lint/test/build。
- **验收标准：** ① 满足规格 6.8 与 AC-UI-006~008；② 旧响应不能覆盖新选择；③ 窄屏仍可选择日期、Tab 和展开明细。
- **潜在风险：** jsdom 无法完全代表真实 ECharts 布局；需要后续真实浏览器验收。
- **依赖：** T43、T44、T45、T46、T47。
- **规模：** M（5 个文件）。

## 检查点 G4（T48）

- [x] 全部前端自动测试、lint、build 通过。
- [x] 真实浏览器测试尚未执行时明确标记，不自行启动服务。

## 阶段 H：系统级验收与交付

### T49：建立单模块隔离矩阵和安全配置检查

- [x] **修改文件范围：** `backend/backend/tests/test_module_isolation.py`、`backend/backend/tests/test_security_settings.py`、`backend/backend/tests/test_source_policy.py`、`scripts/check_module_matrix.sh`、`.gitignore`。
- **具体结果：** 自动验证五种 `core + 单业务 App` 配置的 check、迁移路由、命令发现、测试标签和 URL；扫描跨业务 import、跨库关系、禁用 URL、危险数据源和生产安全配置。
- **测试方式：** 运行隔离矩阵脚本、Django 测试、生产配置 check、源码扫描和 `git diff --check`。
- **验收标准：** ① 满足 AC-MOD-001~007；② 满足 AC-SRC-001 与 AC-SEC-001/004/005/006；③ 删除一个模块的历史状态不影响 admin/core。
- **潜在风险：** 文本扫描误报/漏报动态导入；测试矩阵耗时较长；脚本不应硬编码开发者绝对路径。
- **依赖：** T18、T23、T28、T31、T34、T38、T48。
- **规模：** M（5 个文件）。

### T50：完成部署说明、验收追踪和受控运行时验收

- [x] **修改文件范围：** `README.md`、`docs/deployment.md`、`docs/acceptance/a-share-market-review-traceability.md`、`tasks/todo.md`（仅更新完成状态）。
- **具体结果：** 记录本地/阿里云 `.env` 配置、六库迁移顺序、管理员创建、五组 crontab 命令、静态文件/HTTPS安全要求、手动备份责任和回滚方式；将全部规格 AC 映射到测试或人工证据。
- **测试方式：** 执行后端 check/migrations dry-run/test、前端 test/lint/build、隔离矩阵、仓库扫描和 `git diff --check`；真实网页/API 验收前先询问用户服务地址，获准后验证登录、默认页、四个 Tab、状态与 admin。
- **验收标准：** ① 102条规格验收标准均有证据或明确待用户环境项；② 不声称已执行未获准的 Web 测试；③ 文档明确无自动备份、清理和外部通知。
- **潜在风险：** 阿里云文件权限、HTTPS反代和 crontab 环境与本地不同；没有现成服务时无法完成真实运行时证据。
- **依赖：** T49。
- **规模：** M（4 个文件）。

## 最终检查点（T49~T50）

- [x] 后端 `check`、迁移检查、全部测试通过。
- [x] 前端 test、lint、build 通过。
- [x] 五种单模块配置全部通过。
- [x] 仓库无真实凭据、SQLite、缓存、日志或构建产物。
- [x] 所有规格验收标准已有追踪证据。
- [ ] 用户完成计划批准后的最终功能评审。
