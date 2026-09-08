# 仓库指南

## 项目结构与模块组织

这是一个精简的 Django 后端。`backend/manage.py` 是命令入口；`backend/backend/` 包含设置、URL 和部署入口。在 `backend/` 内创建应用，并将模型、视图、服务、迁移和测试放在一起。不要提交数据库、虚拟环境、缓存或 `.env`。

## 开发命令

在 `backend/` 目录下运行：

- `python manage.py runserver` —— 启动开发服务器。
- `python manage.py migrate` / `makemigrations` —— 应用或生成迁移。
- `python manage.py test` —— 运行测试。
- `python manage.py check` —— 校验配置。

使用虚拟环境；提交依赖。

## 编码与测试规范

遵循 PEP 8 和四空格缩进。模块与函数使用 `snake_case`，类使用 `PascalCase`，应用名使用小写。将业务逻辑放在 services 中。使用 Django 的 `TestCase`；测试文件命名为 `test_*.py`，方法命名为 `test_<行为>`。覆盖回归场景。

如果需要访问网页或者发送web api请求进行测试，需要提前询问是否已有本地开发环境部署好的前后端服务及服务地址，如果没有，不要自行搭建测试环境。

## 配置

所有开发与测试配置值都必须从根目录的 `.env` 读取并写入，包括凭据、URL、开关和超时时间。切勿在代码、测试、fixtures 或命令中硬编码配置。保持 `.env` 不被跟踪，并在 `.env.example` 中记录安全占位符。生产环境必须禁用 `DEBUG`、配置 `ALLOWED_HOSTS`，并从 `.env` 加载 Django 密钥。

## 数据源

所有个股和板块数据，都需要先通过 python manage.py 命令从数据源获取，然后存入本地数据库，再通过 web api 从本地数据库获取。通过 web api 获取数据时，优先使用本地文件系统缓存，然后使用本地数据库，最后使用数据源。

### 个股数据源

所有个股数据，都需要使用其同花顺 Python SDK。不要使用爬虫、浏览器自动化、原始 HTTP。查阅[同花顺文档](https://fuyao.aicubes.cn/llms-full.txt)，并从 `.env` 加载 SDK 设置。

### 板块资金流数据源

这些请求仅被批准用于板块资金流数据，而非个股数据。这些请求相关的url和参数，也必须是可配置的，并从 `.env` 加载

#### 东方财富

**GET URL:** `https://push2.eastmoney.com/api/qt/clist/get`

参数示例：

- `po`：`1` 表示流入排名；`0` 表示流出排名
- `np=1`、`fltt=2`、`invt=2`、`fid=f62`、`stat=1`、`pn=1`、`pz=50`
- `ut=8dec03ba335b81bf4ebdf7b29ec27d15`
- `fs=m:90+s:8+f:!50`
- `fields=f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124`

#### 开盘啦

**POST URL:** `https://apphwshhq.longhuvip.com/w1/api/index.php`

以 `application/x-www-form-urlencoded` 请求体发送参数示例：

- `Order=1`、`a=RealRankingInfo`、`c=ZhiShuRanking`、`st=80`
- `PhoneOSNew=1`、`VerSion=5.23.0.4`、`apiv=w44`
- `Type=1`、`ZSType=7`
- `Index`：页偏移量（`0`、`80`、`160`，...）
- `DeviceID`：来自 `.env` 的 `KPL_DEVICE_ID` 的值
- 当 `.env` 中对应的值非空时，添加来自 `KPL_USER_ID` 的 `UserID` 和来自 `KPL_TOKEN` 的 `Token`。

## 提交与拉取请求

使用祈使语气的提交信息。拉取请求必须总结变更、列出验证方式、关联 issue，并明确指出迁移、配置或上游契约的变更。对于可见的变更，请附上截图。
