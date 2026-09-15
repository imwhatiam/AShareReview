---
name: hithink-market-dumps
description: 用同花顺的 market-dumps 一次性拿到全市场日 K —— 当逐只请求的 /api/a-share/prices/historical 因为限流跑不动、或需要全市场历史数据做回补/重建时使用。覆盖三个 dump 端点的准确路径与鉴权、预签名链接的时效、Parquet 的真实 schema 与口径（未复权）、与项目「每只每天都写一行」口径的差异、以及不装 pyarrow 也能核对文件内容的方法。当用户说"同花顺能不能一次获取所有数据""逐只历史接口被限流""能不能批量拉全市场日线""market-dumps 怎么用""批量回补历史行情"时使用。
version: 1.1.0
origin: custom
agent_created: true
display_name: "同花顺全市场导出与限流"
display_name_en: "Hithink Market Dumps & Throttling"
---

# 同花顺全市场导出（market-dumps）与限流口径

## 0. 先记住那条硬约束

`GET /api/a-share/prices/historical` —— 也就是本仓库 `init_stock_daily_prices` 用的端点 —— 官方原文：

> **接口层强约束：每次请求仅一个 thscode**，且 `[start, end]` 窗口跨度不超过 10 年。
> `thscode` … **不接受逗号**。多标的请分多次请求。

所以**逐只请求是设计使然，没有"一次取全市场"的参数可调**。想一次拿完，只能换端点，不是改参数。

`get_historical_prices()` 里那个 `'offset': 0` 是文档没有的字段（文档只列 thscode/interval/start/end/adjust），实测被忽略不报错 —— 别把它当成"分页能力"。

## 1. 两条"一次拿全市场"的路子

### A. `/api/a-share/prices/snapshot` —— 已经在本仓库里用（`refresh_intraday_quotes`）

省略 `thscodes`、按 `limit`/`offset` 遍历**完整 A 股代码表**，约 6 页（limit=1000）就覆盖全市场，约 2 秒。返回 `open/high/low/last_price/prev_price/volume/turnover/price_change_ratio_pct`，**收盘后跑就等于全市场当日收盘数据**。

- 6 次请求 vs 5,573 次请求 —— 这是 `refresh_intraday_quotes`（每天的写入路径）与 `init_stock_daily_prices`（每周日的全量校正）耗时差约 200 倍的真正原因。**日常链路已经全部走快照，"逐只历史"只在一周一次的校正里出现。**
- 口径差异见 `docs/ops/manage-commands.md` §5.5（`volume`/`turnover` 低位有上游舍入；停牌股 `last_price` 为 null）。
- 它是**当天**数据；历史回补不行。

### B. `/api/dump/market-dumps/*` —— 整库 Parquet 直下（本项目尚未使用）

| kind | 内容 | dump_id |
|---|---|---|
| `daily-k-10d` | 全 A 股**最近 10 个交易日**日 K（官方定位：高频增量同步） | `a_share_daily_k_1d_none_10d` |
| `daily-k` | 全 A 股 **10 年**日 K | `a_share_daily_k_1d_none_10y` |
| `adjustment-factors` | 全 A 股**全部**复权因子事件（分红/送股/配股） | `a_share_adjustment_factors_event_none_all` |

```bash
# 正确路径（API Key）：/api/dump/...  ← 注意必须有这个 /api 前缀
GET {HITHINK_FINANCE_BASE_URL}/api/dump/market-dumps/daily-k-10d/download-url
Header: X-api-key: <HITHINK_FINANCE_API_KEY>
```

**几个必须知道的点：**

- **`/dump/...`（不带 api）是网页入口**，用登录 Cookie；用 API Key 打它会拿到 Docusaurus 的 HTML 文档页（HTTP 200 + `<html>`），看起来"成功了"其实什么都没有。别被 200 骗了。
- 返回 `data.presigned_url`（S3）+ `data.presigned_url_expires_at`，**有效期约 5 分钟**，官方明说不要持久化/缓存，每次用之前重新取。要下载就**取完链接立刻 GET**。
- URL 里的 release 目录名就是**数据版本日**，形如 `.../market-dump/daily_k/releases/<YYYYMMDD>/a_share_daily_k_1d_none_10d_<YYYYMMDD>.parquet` —— **当天收盘后该版本已经存在**，因此"当天缺数据"时它是一条可用的兜底通道。
- 中文名 `name` 不在文件里，要自己配 `/api/meta/tickers/list` 解析。

**实测 schema（`daily-k-10d`，纯 Python 读页脚得到，非文档抄录）：**

| 列 | 类型 | 实测值域 |
|---|---|---|
| `thscode` | BYTE_ARRAY | `000001.SZ` .. `920992.BJ`（含北交所） |
| `currency` | BYTE_ARRAY | 恒 `CNY` |
| `interval` | BYTE_ARRAY | 恒 `1d` |
| `adjusted` | BYTE_ARRAY | **恒 `none`（未复权）** |
| `date_ms` | INT64 | 该份为连续 10 个自然日（`10d` 的含义） |
| `open/high/low/close_price` | DOUBLE | — |
| `volume` / `turnover` | DOUBLE | — |

文件编码：**ZSTD + PLAIN_DICT（字典）+ BIT_PACKED**，`PAR1` magic，单 row group。

## 2. 采用 dump 前必须处理的三处口径差异

1. **行数口径不同。** 本仓库 `_build_daily_prices()` 对**每只股票每个交易日都写一行**，没有成交就写全 NULL + `has_valid_trade=False`（所以库里每天恒 5,571 行）。dump 实测 10 天共 **55,489 行 ≈ 5,549 只/日** —— 当天没有 bar 的标的（停牌等）**在 dump 里根本不出现**。直接导入会让每天的 row 数少约 22 行，并且 `pre_close`（= 上一个 has_valid_trade=True 的收盘）的链条需要自己维护。**必须补空行**，否则口径变了。
2. **复权口径是 `none`。** 需要复权序列就再取 `adjustment-factors` 那个 dump 自己算。至于本仓库现在逐日 `adjust=forward` + **单日窗口**（`start=end=trade_date`）拿到的是不是等价于原值 —— **理论上等价，但必须实测逐字段对拍**，不能只看文档就替换。
3. **新增依赖。** `backend/requirements.txt` 只有 Django / requests / chinese-calendar。读 Parquet 要么加 `pyarrow`/`pandas`，要么自带 reader。**只核对元数据（行数/列/统计）不需要依赖**，见 §3。

## 3. 不装任何依赖也能核对 dump 内容

Parquet 的页脚是 `<data><4 字节小端元数据长度><PAR1>`，元数据本身是 **Thrift compact** 编码。手写 ~90 行的解 reader 就能拿到 `num_rows`、全部列名/物理类型、以及**每列的 min/max 统计**（足以证明"覆盖哪些日期、复权口径是什么、thscode 范围"）。

用 `scripts/read_parquet_footer.py`：

```bash
python scripts/read_parquet_footer.py tests/_dump_daily_k_10d.parquet
```

要点与坑：

- 只读**页脚**，所以不用解数据页、不用 zstd、不用任何第三方库。
- INT64 的统计值是 8 字节小端；BYTE_ARRAY 的统计值就是原始字节（`adjusted` 的 min == max == `b'none'` 就是这么读出来的，一眼定口径）。
- 想**逐日行数**就得解数据页了：ZSTD 压缩 + 字典编码，Python 3.14 有标准库 `compression.zstd`（PEP 784），3.13 没有 —— 到这一步才真的需要额外能力，先问值不值。
- 探针**不要放 `/tmp`** 跑（`sys.path[0]` 会被污染）；放仓库 `tests/`，`_` 前缀不会被 `manage.py test` 收集，用完删。

## 4. 限流的官方口径（直接决定重试策略）

官方原文：

> 本服务**当前不限制累计调用次数**。… 服务可能依据**实时负载**动态调整限流策略；HTTP 429 响应或 `code=4001` 均表示触发限流。此时请**降低并发量和请求频率，避免立即连续重试**，并在稍后重新发起请求。

实测印证：一次在 64% 处被限流失败（耗时 625s）；**隔约 40 分钟再试，反而在 28% 处就死了（165s）**；随后连 `/prices/snapshot` 也被拒。⇒ 失败后**不要马上重试**，隔 30~60 分钟以上；两条端点会**一起**被限，换端点不是规避手段。

排错顺序（对应 `backend-dataset-diagnosis` 技能 §4.5）：先确认是「整批输入没落库」，再决定是等配额还是换通道，**别去改读路径**。

## 5. 边界

- 只走官方 REST/MCP 接口，不爬页面、不上浏览器自动化。
- API Key 只从 `.env` 读；探针里**不要打印完整预签名 URL**（含临时凭据），打 host + 文件名就够。
- 临时下载的 Parquet 放仓库 `tests/`，用完删（1 MB 量级，随取随删）。
