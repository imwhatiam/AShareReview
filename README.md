# A 股市场复盘

将开盘啦、东方财富板块资金流和三个盘后分析模块整合为一个 Django + React 应用。业务模块通过静态注册表启用，彼此没有代码或数据库依赖；它们共同依赖不可删除的 `core` 基础库。

## 模块

| 模块 | Django App | API 前缀 | 数据来源/用途 |
| --- | --- | --- | --- |
| 开盘啦板块资金流 | `kaipanla` | `/api/kaipanla/` | 开盘啦板块资金流 |
| 东方财富板块资金流 | `eastmoney` | `/api/eastmoney/` | 东方财富板块资金流 |
| 大涨跌幅与大成交量个股 | `stock_moves` | `/api/stock-moves/` | 本地公共日行情分析 |
| 板块动量 | `sector_momentum` | `/api/sector-momentum/` | 本地日行情与开盘啦父行业关系分析 |
| 百日新高新低占比 | `hundred_day` | `/api/hundred-day/` | 本地日行情与开盘啦父行业关系分析 |

前端登录成功后默认打开“板块资金流 → 开盘啦”。东方财富上游出现 403、429、超时或屏蔽是可接受的独立失败：保留旧数据；若没有旧数据，该子页显示准备中或空状态，其他模块不受影响。

## 快速开始

1. 复制根目录 `.env.example` 为根目录 `.env`，填写 Django 密钥、允许访问的域名、同花顺 REST API Key、开盘啦配置及数据库/缓存路径。不要提交 `.env`。
2. 建立可写的 `backend/data/`、`backend/cache/` 和 `backend/data/locks/` 目录。
3. 在 `backend/` 中安装 `requirements.txt` 的依赖，并按 [部署说明](docs/deployment.md) 初始化六个 SQLite 数据库。
4. 首次且仅首次部署时，先同步股票主数据、交易日和开盘啦行业关系，再执行：

   ```bash
   python manage.py init_stock_daily_prices --years 1
   ```

   此命令只初始化截至执行日的一年公共前复权日行情。后续日常任务只能使用 `sync_stock_daily_prices --date YYYY-MM-DD`，Web API 不会触发初始化或全市场同步。
5. 在 `frontend/` 安装依赖并构建前端；生产环境使用 HTTPS 反向代理同时提供前端静态站点和 Django API。

## 开发与验证

从 `backend/` 目录运行：

```bash
python manage.py check
python manage.py test
```

从仓库根目录运行单模块隔离矩阵（不会访问上游）：

```bash
./scripts/check_module_matrix.sh
```

前端验证从 `frontend/` 目录运行：

```bash
npm test -- --run
npm run lint
npm run build
```

详细的部署、crontab、恢复和人工验收步骤见 [docs/deployment.md](docs/deployment.md)；规格到证据的完整映射见 [docs/acceptance/a-share-market-review-traceability.md](docs/acceptance/a-share-market-review-traceability.md)。
